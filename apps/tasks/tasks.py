"""
Celery tasks for the tasks app.
This file will contain task functions that work with TaskRun model.
"""
import logging
import asyncio
import os
import sys
import json
import random
import math
import re
from html import unescape
from html.parser import HTMLParser
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from asgiref.sync import sync_to_async
from celery import shared_task
from django.db import close_old_connections
from django.utils import timezone
from playwright.async_api import async_playwright, Browser, BrowserContext, Page
import aiohttp

logger = logging.getLogger(__name__)

# ============================================================================
# VINTED SCRAPER CONSTANTS (from .env)
# ============================================================================
COMPLETED_STATUSES = ["Order completed!", "Beställning slutförd.", "Manually marked as completed.", "Die Transaktion wurde als abgeschlossen markiert.", "Order completed successfully. The buyer accepted the item.", "Transaktion erfolgreich beendet.", "Payment successful!", "Zahlung abgeschlossen!"]

LOGIN_CHECK_URL = "https://www.vinted.de/"
LOGIN_URL = "https://www.vinted.de/member/login/email"
LOGIN_URL_FRAGMENT = "/member/login/email"
LOGIN_TIMEOUT = 120000  # 2 minutes for manual login
PAGE_LOAD_TIMEOUT = 60000  # 1 minute for page loads
REFRESH_COOKIES_AFTER_N_CONV = 100
PER_PAGE = 50

# Retry configuration
MAX_RETRY_ATTEMPTS = 3
RETRY_BACKOFF_BASE_SEC = 2
RETRY_BACKOFF_MAX_SEC = 30

# Get credentials from .env
EMAIL = os.getenv('VINTED_EMAIL')
PASSWORD = os.getenv('VINTED_PASSWORD')


class VintedCompletionPermanentError(Exception):
    """Non-retryable Vinted completion failure."""


class VintedCompletionRetryableError(Exception):
    """Retryable Vinted completion failure."""


class MetaDescriptionParser(HTMLParser):
    """Small HTML parser to extract the first meta description tag."""

    def __init__(self):
        super().__init__()
        self.description: Optional[str] = None

    def handle_starttag(self, tag, attrs):
        if self.description is not None or tag.lower() != "meta":
            return

        attrs_dict = {
            str(key).lower(): value
            for key, value in attrs
            if key and value is not None
        }
        if attrs_dict.get("name", "").lower() == "description":
            self.description = attrs_dict.get("content")

# ============================================================================
# VINTED SCRAPER UTILITY FUNCTIONS
# ============================================================================

async def save_cookies(context: BrowserContext, filepath: str):
    """Save browser cookies to file."""
    try:
        cookies = await context.cookies()
        with open(filepath, 'w') as f:
            json.dump(cookies, f, indent=2)
        logger.info(f"✓ Cookies saved to {filepath}")
    except Exception as e:
        logger.warning(f"⚠️  Failed to save cookies: {e}")


async def load_cookies(context: BrowserContext, filepath: str) -> bool:
    """Load cookies from file into browser context."""
    try:
        if not os.path.exists(filepath):
            return False
        
        with open(filepath, 'r') as f:
            cookies = json.load(f)
        
        await context.add_cookies(cookies)
        logger.info(f"✓ Loaded {len(cookies)} cookies from {filepath}")
        return True
    except Exception as e:
        logger.warning(f"⚠️  Failed to load cookies: {e}")
        return False


async def is_logged_in(page: Page) -> bool:
    """Check if user is logged in by checking current URL."""
    current_url = page.url
    
    indicators = ["Sign up | Log in", "Registrieren | Einloggen"]
    login_indicators = 0
    for ind in indicators:
        login_indicators += await page.locator(f'text="{ind}"').count()
    
    # If we're on the home page and not redirected to login, we're logged in
    if current_url == LOGIN_CHECK_URL and LOGIN_URL_FRAGMENT not in current_url and login_indicators == 0:
        return True
    
    # If redirected to login page, not logged in
    if LOGIN_URL_FRAGMENT in current_url:
        return False
    
    return False


async def wait_for_manual_login(page: Page, timeout: int) -> bool:
    """Wait for user to manually log in."""
    logger.info("\n" + "=" * 80)
    logger.warning("⚠️  MANUAL LOGIN REQUIRED")
    logger.info("=" * 80)
    logger.warning("Please log in to Vinted in the browser window.")
    logger.warning("The script will continue automatically once you're logged in.")
    logger.info("=" * 80)
    
    start_time = asyncio.get_event_loop().time()
    
    while (asyncio.get_event_loop().time() - start_time) < (timeout / 1000):
        await asyncio.sleep(2)
        
        if await is_logged_in(page):
            logger.info("\n✓ Login detected! Continuing...")
            return True
    
    logger.warning("\n✗ Login timeout reached.")
    return False


async def retry_with_backoff_async(func, max_attempts=MAX_RETRY_ATTEMPTS):
    """Retry function with exponential backoff."""
    attempt = 0
    error = None
    
    while attempt < max_attempts:
        try:
            result = await func()
            return True, result, None
        except Exception as e:
            error = str(e)
            logger.warning(f"⚠️  Error: {error}")
            
            # Check for rate limit error
            refill_ms = None
            try:
                if "refillIn" in str(e):
                    payload = json.loads(str(e).split(":", 1)[-1].strip())
                    refill_ms = payload.get("refillIn")
                    if refill_ms:
                        refill_ms = float(refill_ms) + 5000
            except:
                pass
            
            if refill_ms is not None:
                wait = refill_ms / 1000
                logger.warning(f"⏳ Rate limit hit. Waiting {wait:.1f} seconds...")
            else:
                wait = min(RETRY_BACKOFF_MAX_SEC, RETRY_BACKOFF_BASE_SEC * (2 ** attempt))
                wait = wait * (0.5 + random.random())
                logger.warning(f"⏳ Retrying in {wait:.1f} seconds (attempt {attempt + 1}/{max_attempts})...")
            
            await asyncio.sleep(wait)
            attempt += 1
    
    return False, {}, error


async def close_old_connections_async():
    """Close stale Django DB connections from async code before ORM access."""
    await sync_to_async(close_old_connections, thread_sensitive=True)()


def initialize_task_run_logger(task_run, logger_title: str):
    """Create the per-run log file and return a dedicated logger."""
    from scripts.utils import get_run_logger

    if not task_run.logs_file:
        from django.core.files.base import ContentFile

        log_filename = f"taskrun_{task_run.id}.log"
        task_run.logs_file.save(log_filename, ContentFile(""))
        close_old_connections()
        task_run.save(update_fields=['logs_file'])

    log_path = task_run.logs_file.path
    run_logger = get_run_logger(task_run.id, log_path)
    run_logger.info(logger_title)
    return run_logger


# ============================================================================
# VINTED SCRAPER CLASS
# ============================================================================

class VintedScraperPlaywright:
    def __init__(self, base_url: str = "https://www.vinted.de", headless: bool = False, cookies_file_path: Optional[str] = None, run_logger: Optional[logging.Logger] = None):
        self.base_url = base_url
        self.headless = headless
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None
        self.output_csv = None
        self.output_json = None
        self.cookies_file_path = cookies_file_path  # Store as instance variable (like COOKIES_FILE in original)
        self.api_session: Optional[aiohttp.ClientSession] = None
        self.item_description_cache: Dict[str, Optional[str]] = {}
        self.logger = run_logger or logger  # Use per-run logger if provided, else module-level
    
    async def setup_browser(self):
        """Initialize Playwright browser."""
        self.logger.info("Setting up browser...")
        self.playwright = await async_playwright().start()
        
        # Launch browser with realistic settings
        self.browser = await self.playwright.chromium.launch(
            headless=self.headless,
            args=[
                '--disable-blink-features=AutomationControlled',
                '--no-sandbox',
                '--disable-dev-shm-usage'
            ]
        )
        
        # Create context with realistic viewport and user agent
        self.context = await self.browser.new_context(
            viewport={'width': 1280, 'height': 720},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            locale='de-DE',
            timezone_id='Europe/Berlin'
        )
        
        # Remove webdriver flag
        await self.context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
        """)
        
        self.page = await self.context.new_page()
        self.logger.info("✓ Browser ready")
    
    async def login(self) -> bool:
        """Handle login process - load cookies or wait for manual login."""
        self.logger.info("\n" + "=" * 80)
        self.logger.info("🔐 LOGIN PROCESS")
        self.logger.info("-" * 80)
        
        # Try to load existing cookies (only if cookies_file_path is provided)
        cookies_loaded = False
        if self.cookies_file_path:
            cookies_loaded = await load_cookies(self.context, self.cookies_file_path)
        
        if cookies_loaded:
            self.logger.info("✅ Cookies loaded. Checking session...")
            await self.page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=PAGE_LOAD_TIMEOUT)
            await asyncio.sleep(5)
            
            if await is_logged_in(self.page):
                self.logger.info("✅ Session is valid.")
                return True
            else:
                self.logger.warning("⚠️  Session expired.")
                # Try automatic login if credentials provided
                if EMAIL and PASSWORD:
                    if await self.auto_login(EMAIL, PASSWORD):
                        if self.cookies_file_path:
                            await save_cookies(self.context, self.cookies_file_path)
                        return True
                    else:
                        self.logger.warning("⚠️  Falling back to manual login...")
                
                # Fall back to manual login
                self.logger.warning("⚠️  Session expired. Please log in manually.")
                if not await wait_for_manual_login(self.page, LOGIN_TIMEOUT):
                    self.logger.warning("❌ Login failed. Exiting.")
                    return False
                if self.cookies_file_path:
                    await save_cookies(self.context, self.cookies_file_path)

                if not await wait_for_manual_login(self.page, LOGIN_TIMEOUT):
                    self.logger.warning("❌ Login failed. Exiting.")
                    return False
                if self.cookies_file_path:
                    await save_cookies(self.context, self.cookies_file_path)
        else:
            if EMAIL and PASSWORD:
                if await self.auto_login(EMAIL, PASSWORD):
                    if self.cookies_file_path:
                        await save_cookies(self.context, self.cookies_file_path)
                    return True
                else:
                    self.logger.warning("⚠️  Falling back to manual login...")
            
            # Fall back to manual login
            await self.page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=PAGE_LOAD_TIMEOUT)
            await asyncio.sleep(5)
            
            if not await wait_for_manual_login(self.page, LOGIN_TIMEOUT):
                self.logger.warning("❌ Login failed. Exiting.")
                return False
            if self.cookies_file_path:
                await save_cookies(self.context, self.cookies_file_path)
        
        self.logger.info("✅ Login successful!")
        return True
    
    async def refresh_cookies(self) -> Dict[str, str]:
        """Refresh cookies from browser context."""
        self.logger.info("🔄 Refreshing cookies...")
        
        if not self.page:
            # Reopen page if closed
            self.page = await self.context.new_page()
        
        # Navigate to main page to refresh session
        await self.page.goto(f"{self.base_url}/", wait_until="domcontentloaded", timeout=PAGE_LOAD_TIMEOUT)
        await asyncio.sleep(10)
        
        await self.page.goto(f"{self.base_url}/", wait_until="domcontentloaded", timeout=PAGE_LOAD_TIMEOUT)
        await asyncio.sleep(10)
        
        # Save refreshed cookies (only if cookies_file_path is provided)
        if self.cookies_file_path:
            await save_cookies(self.context, self.cookies_file_path)
        
        # Get fresh cookies
        cookies = {}
        for cookie in await self.context.cookies():
            cookies[cookie['name']] = cookie.get('value', None)
        
        self.logger.info("✓ Cookies refreshed")
        return cookies

    async def get_cookies_dict(self) -> Dict[str, str]:
        """Get browser cookies as dictionary."""
        cookies = {}
        for cookie in await self.context.cookies():
            cookies[cookie['name']] = cookie.get('value', None)
        
        return cookies
    
    async def _ensure_session(self):
        """Ensure self.api_session exists and is open. Rebuild from browser cookies if needed."""
        if self.api_session is not None and not self.api_session.closed:
            return  # Session is healthy
        
        self.logger.warning("⚠️  api_session is None or closed — rebuilding from browser cookies...")
        try:
            cookies = await self.get_cookies_dict()
        except Exception:
            cookies = {}

        self.api_session = aiohttp.ClientSession(
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7",
                "Referer": f"{self.base_url}/inbox",
                "Origin": self.base_url,
            },
            cookies=cookies
        )
        self.logger.info("✓ api_session rebuilt successfully")

    async def api_request(self, url: str, method: str = "GET") -> Any:
        """
        Executes an API request using self.api_session.
        If cookies were refreshed, self.api_session is updated.
        Always ensures the session is alive before making a request.
        """
        # Guard: rebuild session if it was left closed by a previous failed recovery
        await self._ensure_session()

        async with self.api_session.request(method, url) as response:
            if response.status == 429:
                try:
                    error_data = await response.json()
                    raise Exception(f"Rate limit: {json.dumps(error_data)}")
                except:
                    raise Exception("Rate limit (429)")

            if response.status in (400, 401):
                self.logger.warning(f"Auth error {response.status} on {url} → refreshing cookies...")

                try:
                    new_cookies = await self.refresh_cookies()
                    if self.api_session is not None and not self.api_session.closed:
                        await self.api_session.close()
                    self.api_session = aiohttp.ClientSession(
                        headers={
                            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                            "Accept": "application/json, text/plain, */*",
                            "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7",
                            "Referer": f"{self.base_url}/inbox",
                            "Origin": self.base_url,
                        },
                        cookies=new_cookies
                    )
                    self.logger.info("Retrying request with fresh cookies...")
                    # Retry once with new session
                    async with self.api_session.request(method, url) as retry_resp:
                        retry_resp.raise_for_status()
                        return await retry_resp.json()
                except Exception as e:
                    self.logger.error(f"Failed even after refresh: {e}")
                    # Session might be closed — _ensure_session will rebuild it on next call
                    raise

            # Normal success or other error
            response.raise_for_status()
            return await response.json()
    
    async def get_conversation_details(self, conversation_id: int) -> Optional[Dict]:
        """Fetch conversation details to get transaction ID."""
        await asyncio.sleep(1)
        url = f"{self.base_url}/api/v2/conversations/{conversation_id}"
        return await self.api_request(url)
    
    async def get_transaction_details(self, transaction_id: int) -> Optional[Dict]:
        """Fetch transaction details."""
        await asyncio.sleep(1)
        url = f"{self.base_url}/api/v2/transactions/{transaction_id}"
        return await self.api_request(url)

    async def get_refund_details(self, transaction_id: int) -> Optional[Dict]:
        """Fetch transaction details."""
        await asyncio.sleep(1)
        url = f"{self.base_url}/api/v2/transactions/{transaction_id}/refund"
        return await self.api_request(url)
    
    async def get_escrow_order_details(self, transaction_id: int) -> Optional[Dict]:
        """Fetch escrow order details for detailed pricing breakdown."""
        await asyncio.sleep(1)
        url = f"{self.base_url}/api/v2/escrow_orders/{transaction_id}"
        return await self.api_request(url)

    async def get_tracking_journey(self, transaction_id: int) -> Optional[Dict]:
        """Fetch tracking journey summary for a transaction."""
        await asyncio.sleep(1)
        url = f"{self.base_url}/api/v2/transactions/{transaction_id}/shipment/journey_summary"
        return await self.api_request(url)

    def extract_item_description_from_html(self, html_text: str, item_title: Optional[str]) -> Optional[str]:
        """Extract and normalize an item description from a Vinted item page HTML."""
        if not html_text:
            return None

        parser = MetaDescriptionParser()
        parser.feed(html_text)
        raw_description = parser.description
        if not raw_description:
            return None

        description = re.sub(r"\s+", " ", unescape(raw_description)).strip()
        title = re.sub(r"\s+", " ", unescape(item_title or "")).strip()

        if title:
            prefix = f"{title} - "
            if description[: len(prefix)].casefold() == prefix.casefold():
                description = description[len(prefix):].strip()

        if not description:
            return None

        if title and description.casefold() == title.casefold():
            return None

        return description

    async def fetch_item_page_html(self, item_url: str) -> Optional[str]:
        """Fetch the Vinted item page HTML using the authenticated session."""
        if not item_url:
            return None

        await self._ensure_session()

        request_headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Referer": f"{self.base_url}/inbox",
        }

        async def _request_html() -> str:
            async with self.api_session.get(item_url, headers=request_headers) as response:
                if response.status in (400, 401):
                    self.logger.warning(f"Auth error {response.status} on item page {item_url} → refreshing cookies...")
                    new_cookies = await self.refresh_cookies()
                    if self.api_session is not None and not self.api_session.closed:
                        await self.api_session.close()
                    self.api_session = aiohttp.ClientSession(
                        headers={
                            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                            "Accept": "application/json, text/plain, */*",
                            "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7",
                            "Referer": f"{self.base_url}/inbox",
                            "Origin": self.base_url,
                        },
                        cookies=new_cookies
                    )
                    async with self.api_session.get(item_url, headers=request_headers) as retry_response:
                        retry_response.raise_for_status()
                        return await retry_response.text()

                response.raise_for_status()
                return await response.text()

        success, html_text, error = await retry_with_backoff_async(_request_html)
        if not success:
            self.logger.warning(f"⚠️  Failed to fetch item page {item_url}: {error}")
            return None

        return html_text

    async def get_item_description(
        self,
        item_url: Optional[str],
        item_title: Optional[str],
        purchase_description: Optional[str],
        raw_item_description: Optional[str] = None,
    ) -> Optional[str]:
        """Get an item-specific description from raw payload or the item page, with purchase fallback."""
        normalized_item_title = re.sub(r"\s+", " ", unescape(item_title or "")).strip()
        normalized_purchase_description = re.sub(r"\s+", " ", unescape(purchase_description or "")).strip() or None
        normalized_raw_description = re.sub(r"\s+", " ", unescape(raw_item_description or "")).strip() or None

        if (
            normalized_raw_description
            and normalized_item_title
            and normalized_raw_description.casefold() == normalized_item_title.casefold()
        ):
            normalized_raw_description = None

        if normalized_raw_description:
            return normalized_raw_description

        if not item_url:
            return normalized_purchase_description

        if item_url not in self.item_description_cache:
            html_text = await self.fetch_item_page_html(item_url)
            self.item_description_cache[item_url] = self.extract_item_description_from_html(html_text or "", item_title)

        return self.item_description_cache[item_url] or normalized_purchase_description
    def extract_tracking_info(self, journey_data: Optional[Dict]) -> Dict[str, str]:
        """Extract tracking information from journey summary."""
        tracking_info = {
            "tracking_code": "",
            "tracking_url": "",
            "status": "",
        }
        
        if not journey_data:
            return tracking_info
        
        try:
            journey = journey_data.get("journey_summary", {})
            
            # Get current carrier info
            current_carrier = journey.get("current_carrier", {})
            if current_carrier:
                tracking_info["tracking_code"] = current_carrier.get("tracking_code", "")
                tracking_info["tracking_url"] = current_carrier.get("tracking_url", "")
            
            # Get overall status
            tracking_info["status"] = journey.get("status", "")
            
        except Exception as e:
            logger.warning(f"⚠️  Error extracting tracking info: {e}")
        
        return tracking_info

    async def auto_login(self, email: str, password: str) -> bool:
        """Automatically log in with credentials."""
        try:
            self.logger.warning("🔐 Attempting automatic login...")
            
            # Navigate to login page
            await self.page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=PAGE_LOAD_TIMEOUT)
            await asyncio.sleep(10)
            
            popup_options = [
                # Country selection
                ("Deutschland", "text"),
                ("Germany", "text"),
                ("Allemagne", "text"),
                ("Alemania", "text"),
                # Cookie consent buttons
                ("Alle zulassen", "button"),
                ("Accept all", "button"),
                ("Tout accepter", "button"),
                ("Aceptar todo", "button")
            ]
            
            try:
                for option_text, element_type in popup_options:
                    if element_type == "button":
                        locator = self.page.locator(f'button:has-text("{option_text}")').first
                    else:
                        locator = self.page.locator(f'text="{option_text}"').first
                    
                    if await locator.is_visible(timeout=10000):
                        self.logger.info(f"   Clicking: {option_text}...")
                        await locator.click()
                        await asyncio.sleep(1)
            except:
                pass  # Popups didn't appear or already handled

            # Fill in email/username
            self.logger.info("   Filling email...")
            await self.page.fill('input[name="username"]', email)
            await asyncio.sleep(0.5)
            
            # Fill in password
            self.logger.info("   Filling password...")
            await self.page.fill('input[name="password"]', password)
            await asyncio.sleep(0.5)
            
            # Click submit button
            self.logger.info("   Clicking submit button...")
            await self.page.click('button[type="submit"]')
            
            # Wait for potential captcha or login completion
            self.logger.info("⏳ Waiting for login to complete...")
            self.logger.info("   (If captcha appears, please solve it - 60 seconds available)")
            
            # Monitor login status for 60 seconds
            start_time = asyncio.get_event_loop().time()
            timeout_seconds = 60
            check_interval = 2  # Check every 2 seconds
            
            while (asyncio.get_event_loop().time() - start_time) < timeout_seconds:
                await asyncio.sleep(check_interval)
                
                current_url = self.page.url
                
                # Check if successfully logged in
                if await is_logged_in(self.page):
                    self.logger.info("✅ Automatic login successful!")
                    return True
                
                # Check if still on login page (waiting for captcha or error)
                if LOGIN_URL_FRAGMENT in current_url:
                    elapsed = int(asyncio.get_event_loop().time() - start_time)
                    remaining = timeout_seconds - elapsed
                    self.logger.info(f"   ⏳ Still on login page... ({remaining}s remaining)")
                else:
                    # Navigated somewhere else, check status
                    self.logger.info(f"   Current URL: {current_url}")
            
            # Timeout reached
            self.logger.warning("❌ Login timeout reached (60 seconds)")
            
            # Final check
            if await is_logged_in(self.page):
                self.logger.info("✅ Login successful (completed just in time!)")
                return True
            else:
                self.logger.warning("❌ Automatic login failed")
                return False
                
        except Exception as e:
            self.logger.warning(f"❌ Auto-login error: {e}")
            import traceback
            traceback.print_exc()
            return False

    async def process_conversation(self, conv):
        conv_id = conv.get('id')
        
        # Step 1: Get conversation details
        success, conversation_data, error = await retry_with_backoff_async(
            lambda: self.get_conversation_details(conv_id)
        )
        
        if not success or not conversation_data:
            self.logger.warning(f"⚠️  Skipping conversation {conv_id} - Failed to get conversation details: {error}")
            return None
        
        conversation_data['purchase_amount'] = conv.get('purchase_amount')
        conversation_data['purchase_currency'] = conv.get('purchase_currency')
        conversation_data['purchase_date'] = conv.get('purchase_date')
        
        # Step 2: Extract transaction ID
        conversation = conversation_data.get("conversation", {})
        transaction_info = conversation.get("transaction", {})
        transaction_id = transaction_info.get("id")
        
        if not transaction_id:
            self.logger.warning(f"⚠️  No transaction ID found for conversation {conv_id}")
            return None
        
        self.logger.info(f"   → Transaction ID: {transaction_id}")
        
        # Step 3: Get transaction details
        success, transaction_data, error = await retry_with_backoff_async(
            lambda: self.get_transaction_details(transaction_id)
        )

        if not success or not transaction_data:
            self.logger.warning(f"⚠️  Skipping conversation {conv_id} - Failed to get transaction details: {error}")
            return None

        status_title = transaction_data.get("transaction", {}).get('status_title', '').strip()
        self.logger.info(f"   → Transaction status: {status_title}")

        # Step 4: Get tracking journey
        success, tracking_data, error = await retry_with_backoff_async(
            lambda: self.get_tracking_journey(transaction_id)
        )

        if not success:
            self.logger.warning(f"⚠️  Could not fetch tracking journey: {error}")
            tracking_data = None


        refund_data = {}
        if not status_title:
            # fetching refund data
            success, refund_data, error = await retry_with_backoff_async(
                lambda: self.get_refund_details(transaction_id)
            )
            
            if not success:
                self.logger.warning(f"⚠️  Failed to get refund details: {error}")
                refund_data = None

        # Step 5: Get escrow order details for detailed pricing
        success, escrow_data, error = await retry_with_backoff_async(
            lambda: self.get_escrow_order_details(transaction_id)
        )
        
        if not success:
            self.logger.warning(f"⚠️  Could not fetch escrow order details: {error}")
            escrow_data = None

        # Add transaction_user_status to conversation_data
        conversation_data['transaction_user_status'] = conv.get('transaction_user_status')

        extracted_data = await self.extract_purchase_data(
            conversation_data, transaction_data, tracking_data, refund_data, escrow_data, conv_id
        )
        
        # Print full conversation details with indentation
        if extracted_data:
            self.logger.info("\n" + "=" * 80)
            self.logger.info(f"📋 FULL CONVERSATION DETAILS (ID: {conv_id})")
            self.logger.info("=" * 80)
            self.logger.info(json.dumps(extracted_data, indent=2, ensure_ascii=False, default=str))
            self.logger.info("=" * 80 + "\n")
        
        return extracted_data

    async def extract_purchase_data(
        self, 
        conversation_data: Dict, 
        transaction_data: Dict, 
        tracking_data: Optional[Dict], 
        refund_data: Optional[Dict],
        escrow_data: Optional[Dict],
        conversation_id: int
    ) -> Optional[Dict]:
        """Extract data from conversation and transaction — now with ALL fields needed for Purchases model."""
        if not conversation_data or not transaction_data:
            return None

        try:
            conv = conversation_data.get("conversation", {})
            trans = transaction_data.get("transaction", {})
            refund = refund_data.get('refund', {}) if refund_data else {}
            escrow = escrow_data.get('escrow_order', {}) if escrow_data else {}
            
            opp_user = conv.get("opposite_user", {})
            seller_name = opp_user.get("login", "Unknown")
            seller_id = opp_user.get("id")
            
            # === CONVERSATION ID ===
            conversation_id = conversation_id or conv.get("id")
            
            # === TRANSACTION ID ===
            transaction_id = trans.get("id")
            
            # === TRANSACTION STATUS ===
            transaction_status = trans.get("status")
            transaction_completed = trans.get("is_completed")
            transaction_status_updated_at = trans.get("status_updated_at")
            
            # === BEST ITEM TITLE (priority order) ===
            title = (
                conv.get("transaction", {}).get("item_title") or
                trans.get("removed_item_title") or
                conv.get("subtitle") or
                "Unknown item"
            )
            
            # === DESCRIPTION ===
            description = conv.get("description") or conv.get("subtitle") or ""

            # === PURCHASE PRICE (cleanest source) ===
            price = conversation_data.get('purchase_amount')
            currency = conversation_data.get('purchase_currency')

            # === PURCHASE DATE ===
            created_at = conversation_data.get("purchase_date")
            
            # Try to get purchase date from messages if not available
            if not created_at:
                messages = conv.get("messages", [])
                for msg in reversed(messages):
                    if msg.get("entity_type") == "status_message":
                        entity = msg.get("entity", {})
                        if entity.get("title", "").lower() == "purchase successful":
                            created_at = msg.get("created_at_ts")
                            break

            # fetching items
            order = trans.get('order', {})

            refunded_amount = refund.get('amount') if refund else None
            refunded_currency = refund.get('currency') if refund else None

            status_title = trans.get('status_title', '').strip()
            user_status = conversation_data.get('transaction_user_status')
            
            # Use transaction_user_status for accurate classification for finished states
            status_map = {
                "completed": "completed",
                "waiting": "waiting",
                "failed": "cancelled"
            }
            
            if user_status in status_map:
                status_title = status_map[user_status]
            elif status_title:
                if status_title.lower() == "order completed!":
                    status_title = "completed"
            else:
                status_title = "refunded"
            
            # === TRACKING INFO ===
            tracking_info = self.extract_tracking_info(tracking_data)
            
            # === SHIPMENT INFO ===
            shipment = trans.get('shipment', {})
            shipment_id = shipment.get("id") if shipment else None
            shipment_tracking_code = tracking_info.get("tracking_code") or shipment.get("tracking_code") or ""
            tracking_status = tracking_info.get("status", "")
            tracking_url = tracking_info.get("tracking_url", "")

            # === PRICING DETAILS ===
            # First try from transaction
            first_offer = trans.get('first_offer', {})
            service_fee_obj = trans.get('service_fee', {})
            buyer_debit = trans.get('buyer_debit', {})
            
            item_price = None
            purchase_price = None
            service_fee = None
            shipment_price = None
            total_price_no_tax = None
            total_price = None
            
            # Extract from transaction
            if first_offer and first_offer.get('price') and first_offer.get('currency'):
                item_price = [first_offer.get('price'), first_offer.get('currency')]
            
            if service_fee_obj and service_fee_obj.get('amount') and service_fee_obj.get('currency_code'):
                service_fee = [service_fee_obj.get('amount'), service_fee_obj.get('currency_code')]
            
            if buyer_debit:
                if buyer_debit.get('item_price') and buyer_debit.get('currency'):
                    purchase_price = [buyer_debit.get('item_price'), buyer_debit.get('currency')]
                if buyer_debit.get('total_amount_without_tax') and buyer_debit.get('currency'):
                    total_price_no_tax = [buyer_debit.get('total_amount_without_tax'), buyer_debit.get('currency')]
                if buyer_debit.get('total_amount') and buyer_debit.get('currency'):
                    total_price = [buyer_debit.get('total_amount'), buyer_debit.get('currency')]
            
            # If total_price_no_tax not found, try from offer
            if not total_price_no_tax:
                offer = trans.get('offer', {})
                if trans.get('total_amount_without_tax') and offer.get('currency'):
                    total_price_no_tax = [trans.get('total_amount_without_tax'), offer.get('currency')]
            
            # Extract from shipment
            if shipment and shipment.get('price') and shipment.get('currency'):
                shipment_price = [shipment.get('price'), shipment.get('currency')]
            
            # Try to get from escrow_order if available (most detailed source)
            if escrow:
                payment_data = escrow.get('payment_data', {})
                
                # Service fee from escrow
                escrow_service_fee = payment_data.get('service_fee_price', {})
                if escrow_service_fee and escrow_service_fee.get('price'):
                    service_fee_price = escrow_service_fee.get('price', {})
                    if service_fee_price.get('amount') and service_fee_price.get('currency_code'):
                        service_fee = [service_fee_price.get('amount'), service_fee_price.get('currency_code')]
                
                # Items price from escrow
                escrow_items_price = payment_data.get('items_price', {})
                if escrow_items_price and escrow_items_price.get('price'):
                    items_price_obj = escrow_items_price.get('price', {})
                    if items_price_obj.get('amount') and items_price_obj.get('currency_code'):
                        purchase_price = [items_price_obj.get('amount'), items_price_obj.get('currency_code')]
                        # Use as item_price if not set
                        if not item_price:
                            item_price = purchase_price
                
                # Total price from escrow
                escrow_total = payment_data.get('total_price')
                if escrow_total and escrow_total.get('amount') and escrow_total.get('currency_code'):
                    total_price = [escrow_total.get('amount'), escrow_total.get('currency_code')]
                
                # Shipment price from escrow
                escrow_shipment = payment_data.get('shipment_price', {})
                if escrow_shipment and escrow_shipment.get('price'):
                    shipment_price_obj = escrow_shipment.get('price', {})
                    if shipment_price_obj.get('amount') and shipment_price_obj.get('currency_code'):
                        shipment_price = [shipment_price_obj.get('amount'), shipment_price_obj.get('currency_code')]

            items = []
            order_items = order.get('items', [])
            for item in order_items:
                item_title = item.get('title')
                item_url = item.get('url')
                item_description = await self.get_item_description(
                    item_url=item_url,
                    item_title=item_title,
                    purchase_description=description,
                    raw_item_description=item.get('description'),
                )
                
                # fetching item photos
                photos = []
                for photo in item.get('photos', []):
                    photos.append(photo.get("full_size_url") or photo.get("url"))
                
                price_obj = item.get('price', {})
                item_price_val = price_obj.get('amount')
                item_currency = price_obj.get('currency_code')
                
                items.append({
                    'title': item_title,
                    'description': item_description,
                    'price': item_price_val,
                    'currency': item_currency,
                    'url': item_url,
                    'image_urls': photos
                })
            
            # === CHAT MESSAGES ===
            messages = conv.get("messages", [])
            updated_at = None
            if messages:
                last_message = messages[-1]
                updated_at = last_message.get('created_at_ts')
            
            chat_text = str(messages)
            self.logger.info(f"   → Tracking status: {tracking_status}")

            chat_link = conv.get('conversation_url')
            
            # === UNREAD STATUS ===
            unread = conv.get("unread", False)
            
            # === ORDER STATUS NORMALIZATION ===
            order_status = self._normalize_order_status(transaction_status, status_title)

            return {
                # Identifiers
                "conversation_id": conversation_id,
                "seller_id": seller_id,
                "seller_name": seller_name,
                "transaction_id": transaction_id,
                
                # Transaction status
                "transaction_status": transaction_status,
                "transaction_completed": transaction_completed,
                "transaction_status_updated_at": transaction_status_updated_at,
                "order_status": order_status,
                
                # Product info
                "product": title,
                "description": description,
                
                # Dates
                "purchase_at": created_at,
                "updated_at": updated_at,
                
                # Pricing (as [amount, currency] arrays)
                "item_price": item_price,
                "purchase_price": purchase_price,
                "service_fee": service_fee,
                "shipment_price": shipment_price,
                "total_price_no_tax": total_price_no_tax,
                "total_price": total_price,
                "refunded_amount": [refunded_amount, refunded_currency] if refunded_amount else None,
                
                # Shipment
                "shipment_id": shipment_id,
                "shipment_tracking_code": shipment_tracking_code,
                "tracking_status": tracking_status,
                "tracking_url": tracking_url,
                
                # Chat
                "chat_link": chat_link,
                "chat_messages": chat_text,
                "unread": unread,
                
                # Items
                "items": items,
                
                # Legacy fields for backward compatibility
                "username": seller_name,
                "title": title,
                "status": status_title,
                "purchase_amount": price,
                "purchase_currency": currency,
                "refunded_currency": refunded_currency,
                "purchase_date": created_at,
                "tracking_code": shipment_tracking_code,
            }

        except Exception as e:
            self.logger.warning(f"Error extracting data for conv {conversation_id}: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def _normalize_order_status(self, transaction_status: Optional[int], status_title: str) -> Optional[str]:
        """Normalize order status to match Purchases model choices."""
        status_title_lower = status_title.lower() if status_title else ""
        
        # Map transaction status codes FIRST (most reliable)
        if transaction_status:
            status_map = {
                1: "new",
                440: "returned",
                460: "returned",
                455: "completed",
                450: "completed",  # Very common for completed orders
                230: "waiting",    # Paid, awaiting shipment
                210: "waiting",    # Paid
                500: "uncompleted",
                430: "cancelled",
                510: "cancelled",
                520: "cancelled",
            }
            if transaction_status in status_map:
                return status_map[transaction_status]
        
        # Map status titles (case-insensitive)
        if status_title:
            # Check explicit list defined at top of file
            if any(s.lower() in status_title_lower for s in COMPLETED_STATUSES):
                return "completed"
            
            if "completed" in status_title_lower or "payment successful" in status_title_lower:
                return "completed"
            elif "cancelled" in status_title_lower or "suspended" in status_title_lower:
                return "cancelled"
            elif "returned" in status_title_lower or "return completed" in status_title_lower:
                return "returned"
            elif "refunded" in status_title_lower:
                return "refunded"
            elif "new" in status_title_lower:
                return "new"
            elif "uncompleted" in status_title_lower:
                return "uncompleted"
            elif "shipped" in status_title_lower or "sent" in status_title_lower:
                return "shipped"
            elif "delivered" in status_title_lower or "received" in status_title_lower or "pick-up" in status_title_lower:
                return "delivered"
            elif "waiting" in status_title_lower or "purchase successful" in status_title_lower:
                return "waiting"
        
        # FALLBACK: Match status field behavior - if status_title is empty, assume refunded
        if not status_title:
            return "refunded"
        
        return None

    async def cleanup(self):
        """Close browser and cleanup."""
        self.logger.info("\nCleaning up browser resources...")
        
        # Close API session if initialized
        if getattr(self, "api_session", None) and not self.api_session.closed:
            try:
                await self.api_session.close()
                self.logger.info("✓ API session closed")
            except Exception as e:
                self.logger.warning(f"⚠️  Error closing api_session: {e}")
            finally:
                self.api_session = None

        # Close context (closes all pages)
        if self.context:
            try:
                await self.context.close()
                self.logger.info("✓ Browser context closed")
            except Exception as e:
                self.logger.warning(f"⚠️  Error closing context: {e}")
            finally:
                self.context = None
        
        # Close browser
        if self.browser:
            try:
                await self.browser.close()
                self.logger.info("✓ Browser closed")
            except Exception as e:
                self.logger.warning(f"⚠️  Error closing browser: {e}")
            finally:
                self.browser = None
        
        # Stop playwright
        if self.playwright:
            try:
                await self.playwright.stop()
                self.logger.info("✓ Playwright stopped")
            except Exception as e:
                self.logger.warning(f"⚠️  Error stopping playwright: {e}")
            finally:
                self.playwright = None
        
        self.logger.info("✓ Cleanup complete")

@shared_task(bind=True)
def scheduled_vinted_scraper(self):
    """
    Scheduled wrapper for the Vinted scraper (called by Celery Beat).
    Creates a TaskRun and delegates to fetch_vinted_conversations_task.
    Skips if a scraper is already running.
    """
    from .models import Task, TaskRun

    close_old_connections()

    try:
        task = Task.objects.get(slug='vinted-conversation-scraping')
    except Task.DoesNotExist:
        logger.error("Scheduled scraper: Task 'vinted-conversation-scraping' not found in DB.")
        return

    # Skip if already running
    running = TaskRun.objects.filter(task=task, status__in=['PENDING', 'RUNNING']).first()
    if running:
        logger.info(f"Scheduled scraper: Skipping — TaskRun #{running.id} is already running.")
        return

    # Create a new TaskRun for the scheduled run
    task_run = TaskRun.objects.create(
        task=task,
        started_by=None,  # Scheduled — no user
        status='PENDING',
        input_data={},
        detail='Queued for scheduled execution.',
    )
    
    # Set descriptive title with ID
    task_run.title = f"Scheduled {task.name} task #{task_run.id}"
    close_old_connections()
    task_run.save(update_fields=['title'])
    
    logger.info(f"Scheduled scraper: Created TaskRun #{task_run.id}")

    # Dispatch the actual scraper task
    result = fetch_vinted_conversations_task.delay(task_run_id=task_run.id)
    
    # Save Celery task ID so it can be cancelled
    task_run.celery_task_id = result.id
    close_old_connections()
    task_run.save()


@shared_task(bind=True)
def fetch_vinted_conversations_task(self, task_run_id: int):
    """
    Celery task to run the Vinted scraper.
    
    Args:
        task_run_id: ID of the TaskRun instance to track progress
    """
    from celery.exceptions import SoftTimeLimitExceeded
    
    task_run = None
    try:
        from .models import TaskRun
        from purchases.models import Purchases
        from purchases.adapters import get_adapter
        
        # Get TaskRun and Task instances
        close_old_connections()
        task_run = TaskRun.objects.get(id=task_run_id)
        task = task_run.task
        
        # Update status to RUNNING
        task_run.status = 'RUNNING'
        task_run.started_at = timezone.now()
        task_run.detail = 'Fetching Vinted conversations.'
        close_old_connections()
        task_run.save(update_fields=['status', 'started_at', 'detail'])
        
        logger.info(f"TaskRun #{task_run_id}: Starting Vinted conversation scraper")
        
        run_logger = initialize_task_run_logger(
            task_run,
            f"TaskRun #{task_run_id}: Starting Vinted conversation scraper",
        )
        
        # Extract input_data (days_to_fetch, default: None to fetch all)
        input_data = task_run.input_data or {}
        days_to_fetch = input_data.get('days_to_fetch')
        
        # Read max conversations limit from environment
        max_conversations_env = os.environ.get('VINTED_MAX_CONVERSATIONS', '').strip()
        max_conversations = int(max_conversations_env) if max_conversations_env else None
        if max_conversations:
            logger.info(f"TaskRun #{task_run_id}: Max conversations limit set to {max_conversations}")
        
        # Get cookies_file path from Task (None if not set - no cookies will be used)
        cookies_file_path = None
        logger.info(f"Task cookies file: {task.cookies_file}")
        if task.cookies_file:
            # Get the full path to the cookies file
            cookies_file_path = task.cookies_file.path
            logger.info(f"TaskRun #{task_run_id}: Using cookies file from Task: {cookies_file_path}")
        else:
            logger.info(f"TaskRun #{task_run_id}: No cookies file set - cookies will not be used")
        
        # Initialize progress
        task_run.progress = {
            'conversations_processed': 0,
            'total_conversations': None,  # Will be updated as we go
            'days_fetched': 0 if days_to_fetch is not None else None,  # Start at 0, will be updated as we process conversations
            'current_page': 1,
        }
        close_old_connections()
        task_run.save()
        
        # Run async scraper
        asyncio.run(
            _run_vinted_scraper(
                task_run_id=task_run_id,
                cookies_file_path=cookies_file_path,
                days_to_fetch=days_to_fetch,
                max_conversations=max_conversations,
                run_logger=run_logger,
            )
        )
        
        # Update status to SUCCESS
        close_old_connections()
        task_run.refresh_from_db()
        if task_run.status != 'CANCELLED':
            task_run.status = 'SUCCESS'
            task_run.finished_at = timezone.now()
            task_run.detail = 'Vinted conversations fetched successfully.'
            close_old_connections()
            task_run.save(update_fields=['status', 'finished_at', 'detail'])
            run_logger.info(f"TaskRun #{task_run_id}: Completed successfully")
            logger.info(f"TaskRun #{task_run_id}: Completed successfully")
        
    except TaskRun.DoesNotExist:
        logger.error(f"TaskRun #{task_run_id}: TaskRun not found")
        raise
    except SoftTimeLimitExceeded:
        error_msg = "Task timed out (Soft Time Limit exceeded)"
        logger.error(f"TaskRun #{task_run_id}: {error_msg}")
        try:
            close_old_connections()
            task_run.refresh_from_db()
            if task_run.status != 'CANCELLED':
                task_run.status = 'FAILURE'
                task_run.detail = error_msg
                task_run.finished_at = timezone.now()
                close_old_connections()
                task_run.save(update_fields=['status', 'detail', 'finished_at'])
        except Exception:
            pass
        raise
    except Exception as e:
        logger.error(f"TaskRun #{task_run_id}: Failed - {e}", exc_info=True)
        try:
            close_old_connections()
            task_run.refresh_from_db()
            if task_run.status != 'CANCELLED':
                task_run.status = 'FAILURE'
                task_run.detail = str(e)
                task_run.finished_at = timezone.now()
                close_old_connections()
                task_run.save(update_fields=['status', 'detail', 'finished_at'])
        except Exception:
            pass
        raise
    finally:
        # Final safety check: if task_run is still RUNNING, mark as FAILURE
        # This handles cases where the task might have crashed or been killed
        # without updating its status.
        try:
            if task_run:
                close_old_connections()
                task_run.refresh_from_db()
                if task_run.status == 'RUNNING':
                    task_run.status = 'FAILURE'
                    task_run.detail = "Task stopped unexpectedly"
                    task_run.finished_at = timezone.now()
                    close_old_connections()
                    task_run.save(update_fields=['status', 'detail', 'finished_at'])
                    logger.warning(f"TaskRun #{task_run_id}: Status force-updated to FAILURE in finally block")
        except Exception as e:
            logger.error(f"TaskRun #{task_run_id}: Error in finally block - {e}")


async def _run_vinted_scraper(
    task_run_id: int,
    cookies_file_path: Optional[str],
    days_to_fetch: Optional[int],
    max_conversations: Optional[int] = None,
    run_logger: Optional[logging.Logger] = None,
):
    """
    Async wrapper that runs the Vinted scraper and intercepts data to save to Purchases.
    
    This function:
    1. Creates a scraper wrapper class that extends VintedScraperPlaywright
    2. Overrides get_conversations_via_api to intercept data before saving
    3. Saves data to Purchases model using VintedAdapter
    4. Updates TaskRun progress
    5. Checks for cancellation
    """
    from .models import TaskRun
    from purchases.models import Purchases
    from purchases.adapters import get_adapter
    
    # Get TaskRun for progress updates (using async ORM method)
    await close_old_connections_async()
    task_run = await TaskRun.objects.aget(id=task_run_id)

    async def refresh_task_run():
        await close_old_connections_async()
        await task_run.arefresh_from_db()

    async def save_task_run():
        await close_old_connections_async()
        await task_run.asave()

    async def upsert_purchase(normalized):
        await close_old_connections_async()
        return await Purchases.objects.aupdate_or_create(
            platform='vinted',
            external_id=normalized['external_id'],
            defaults=normalized
        )
    
    # Track processed conversations
    processed_count = [0]  # Use list to allow modification in nested function
    current_page = [1]  # Track current page
    
    # Constants
    SECONDS_PER_DAY = 86400
    
    def calculate_days_fetched(oldest_date: Optional[datetime], days_to_fetch: Optional[int], now: datetime) -> Optional[int]:
        """
        Calculate actual days fetched based on oldest conversation date.
        
        If days_to_fetch is 1, it means today only.
        If days_to_fetch is 2, it means today and yesterday.
        So we calculate how many days from today (inclusive) we've covered.
        """
        if oldest_date is None:
            return 0 if days_to_fetch is not None else None
        
        if days_to_fetch is None:
            return None
        
        # Get today at 00:00:00
        today_start = datetime(now.year, now.month, now.day, 0, 0, 0)
        
        # Get the date of the oldest conversation at 00:00:00
        oldest_date_start = datetime(oldest_date.year, oldest_date.month, oldest_date.day, 0, 0, 0)
        
        # Calculate number of days from today to oldest_date (inclusive)
        # If oldest_date is today: days_fetched = 1
        # If oldest_date is yesterday: days_fetched = 2
        # etc.
        days_diff = (today_start - oldest_date_start).days + 1
        
        # Cap at days_to_fetch
        return min(days_diff, days_to_fetch)
    
    # Create a wrapper class that extends the scraper
    class TaskScraperWrapper(VintedScraperPlaywright):
        """Wrapper that intercepts data and saves to Purchases model."""
        
        def __init__(self, base_url: str = "https://www.vinted.de", headless: bool = False, cookies_file_path: Optional[str] = None, run_logger: Optional[logging.Logger] = None):
            super().__init__(base_url=base_url, headless=headless, cookies_file_path=cookies_file_path, run_logger=run_logger)
            self.api_session: Optional[aiohttp.ClientSession] = None
        
        async def get_conversations_via_api(self, cookies):
            """Override to intercept conversation data and save to Purchases."""
            try:
                # Get adapter
                adapter = get_adapter('vinted')
                
                # Create aiohttp session with cookies (only if cookies are provided)
                session_headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    "Accept": "application/json, text/plain, */*",
                    "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7",
                    "Referer": f"{self.base_url}/inbox",
                    "Origin": self.base_url,
                }
                # Only add cookies if they are provided (not None/empty)
                if cookies:
                    self.api_session = aiohttp.ClientSession(headers=session_headers, cookies=cookies)
                else:
                    self.api_session = aiohttp.ClientSession(headers=session_headers)
                
                now = datetime.now()
                today_start = datetime(now.year, now.month, now.day, 0, 0, 0)
                
                if days_to_fetch is None:
                    # Fetch all conversations - set cutoff_date to a very old date
                    cutoff_date = datetime(1970, 1, 1)
                    self.logger.info(f"TaskRun #{task_run_id}: Fetching all orders (no date limit)")
                else:
                    # If days_to_fetch is 1, fetch today only (cutoff = today at 00:00:00)
                    # If days_to_fetch is 2, fetch today and yesterday (cutoff = yesterday at 00:00:00)
                    # So cutoff = today - (days_to_fetch - 1) days at 00:00:00
                    cutoff_date = today_start - timedelta(days=days_to_fetch - 1)
                    self.logger.info(f"TaskRun #{task_run_id}: Fetching orders from last {days_to_fetch} days (cutoff: {cutoff_date.strftime('%Y-%m-%d %H:%M:%S')})")
                
                page = 1
                PER_PAGE = 50
                REFRESH_COOKIES_AFTER_N_CONV = 100
                ind = 0
                # Track the oldest conversation date to calculate actual days fetched
                oldest_conv_date = None
                
                while True:
                    # Check for cancellation
                    await refresh_task_run()
                    if task_run.status == 'CANCELLED':
                        self.logger.info(f"TaskRun #{task_run_id}: Cancelled at page {page}")
                        await self.api_session.close()
                        return
                    
                    try:
                        await asyncio.sleep(1)
                        
                        url = f"{self.base_url}/api/v2/my_orders?type=purchased&status=all&page={page}&per_page={PER_PAGE}"
                        data = await self.api_request(url)
                        
                        if not data:
                            if page == 1:
                                self.logger.warning(f"TaskRun #{task_run_id}: Failed to fetch orders. API authentication may have failed.")
                            break
                        
                        conversations = data.get("my_orders", [])
                        
                        if not conversations:
                            self.logger.info(f"TaskRun #{task_run_id}: No more orders on page {page}")
                            break
                        
                        self.logger.info(f"TaskRun #{task_run_id}: Page {page}: Found {len(conversations)} conversations")
                        
                        # Update progress with current page (before processing conversations)
                        current_page[0] = page
                        task_run.progress = {
                            'conversations_processed': processed_count[0],
                            'total_conversations': None,
                            'days_fetched': calculate_days_fetched(oldest_conv_date, days_to_fetch, now),
                            'current_page': page,
                        }
                        await save_task_run()
                        
                        for conv in conversations:
                            # Check for cancellation
                            await refresh_task_run()
                            if task_run.status == 'CANCELLED':
                                self.logger.info(f"TaskRun #{task_run_id}: Cancelled at conversation {ind + 1}")
                                await self.api_session.close()
                                return
                            
                            ind += 1
                            
                            # Session refreshing (from original code)
                            if ind % REFRESH_COOKIES_AFTER_N_CONV == 0:
                                await self.api_session.close()
                                cookies = await self.refresh_cookies()
                                
                                self.api_session = aiohttp.ClientSession(
                                    headers={
                                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                                        "Accept": "application/json, text/plain, */*",
                                        "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7",
                                        "Referer": f"{self.base_url}/inbox",
                                        "Origin": self.base_url,
                                    },
                                    cookies=cookies
                                )
                            
                            conv_id = conv.get("conversation_id")
                            if conv_id:
                                # Get price and currency
                                price_obj = conv.get('price', {})
                                price = price_obj.get('amount')
                                currency = price_obj.get('currency_code')
                                purchase_date = conv.get("date", "")[:19].replace("T", " ")
                                
                                conv_data = {
                                    "id": conv_id,
                                    "purchase_amount": price,
                                    "purchase_currency": currency,
                                    "purchase_date": purchase_date,
                                    "transaction_user_status": conv.get("transaction_user_status")
                                }
                                
                                self.logger.info(f"TaskRun #{task_run_id}: [{ind}] Processing conversation ID {conv_id}")
                                
                                # Process conversation (this calls the original method)
                                extracted_data = await self.process_conversation(conv_data)
                                
                                if extracted_data:
                                    updated_at_str = extracted_data.get("updated_at", "")
                                    if updated_at_str:
                                        try:
                                            conv_updated_at = datetime.strptime(f"{updated_at_str[:19]}", "%Y-%m-%dT%H:%M:%S")
                                            self.logger.info(f"TaskRun #{task_run_id}:   → Updated at: {conv_updated_at}")
                                            
                                            # Track oldest conversation date for days progress calculation
                                            if oldest_conv_date is None or conv_updated_at < oldest_conv_date:
                                                oldest_conv_date = conv_updated_at
                                            
                                            # Check if conversation is older than cutoff date
                                            # Compare dates at day level (ignore time)
                                            conv_date_start = datetime(conv_updated_at.year, conv_updated_at.month, conv_updated_at.day, 0, 0, 0)
                                            if days_to_fetch is not None and conv_date_start < cutoff_date:
                                                ind -= 1
                                                self.logger.info(
                                                    f"TaskRun #{task_run_id}: Reached conversations older than "
                                                    f"{days_to_fetch} days (updated_at: {updated_at_str[:19]}). Stopping."
                                                )
                                                await self.api_session.close()
                                                return
                                        except ValueError:
                                            pass  # Invalid date format, continue
                                    
                                    # Save to Purchases model
                                    try:
                                        normalized = adapter.normalize(extracted_data)
                                        
                                        # Create or update Purchases instance
                                        purchase, created = await upsert_purchase(normalized)
                                        
                                        action = "Created" if created else "Updated"
                                        self.logger.info(
                                            f"TaskRun #{task_run_id}: {action} purchase {purchase.external_id} "
                                            f"({ind}/{len(conversations)} on page {page})"
                                        )
                                        
                                        # Update processed count
                                        processed_count[0] = ind
                                        
                                        # Update progress after each conversation
                                        task_run.progress = {
                                            'conversations_processed': processed_count[0],
                                            'total_conversations': None,
                                            'days_fetched': calculate_days_fetched(oldest_conv_date, days_to_fetch, now),
                                            'current_page': page,
                                        }
                                        await save_task_run()
                                        
                                    except Exception as e:
                                        self.logger.error(
                                            f"TaskRun #{task_run_id}: Failed to save conversation "
                                            f"{conv_id}: {e}",
                                            exc_info=True
                                        )
                                        # Continue processing other conversations
                                        continue
                                    
                                    # Check max conversations limit
                                    if max_conversations and processed_count[0] >= max_conversations:
                                        self.logger.info(
                                            f"TaskRun #{task_run_id}: Reached max conversations limit "
                                            f"({max_conversations}). Stopping."
                                        )
                                        await self.api_session.close()
                                        return
                        
                        # Check pagination
                        pagination = data.get("pagination", {})
                        if int(pagination.get("total_pages", 1)) == page:
                            self.logger.info(f"TaskRun #{task_run_id}: Reached last page!")
                            break
                        
                        page += 1
                        continue
                    
                    except Exception as e:
                        self.logger.error(f"TaskRun #{task_run_id}: Error fetching orders on page {page}: {e}", exc_info=True)
                        break
                
                # Close aiohttp session
                await self.api_session.close()
                
                self.logger.info(f"TaskRun #{task_run_id}: Scraping complete! Total conversations processed: {processed_count[0]}")
                
            except Exception as e:
                self.logger.error(f"TaskRun #{task_run_id}: Error in get_conversations_via_api: {e}", exc_info=True)
                raise
        
        async def save_to_file(self, output_csv_path, output_json_path, all_data):
            """Override to prevent file saving - we save to Purchases model instead."""
            # No-op: Do not save to files
            pass
        
        async def scrape_all_data(self, output_csv, output_json):
            """Override scrape_all_data to match original logic exactly."""
            self.logger.info("\n" + "=" * 80)
            self.logger.info("🚀 VINTED DATA SCRAPER")
            self.logger.info("=" * 80)
            self.logger.info(f"📋 Configuration:")
            self.logger.info(f"   Base URL: {self.base_url}")
            self.logger.info(f"   Output CSV: {output_csv}")
            self.logger.info(f"   Output JSON: {output_json}")
            self.logger.info(f"   Cookies file: {self.cookies_file_path or 'None (not using cookies)'}")
            self.logger.info("=" * 80)
            
            await self.setup_browser()
            
            self.output_csv = output_csv
            self.output_json = output_json

            if not await self.login():
                self.logger.warning("❌ Failed to login. Exiting.")
                # Don't cleanup here - let the finally block handle it
                return

            await self.page.goto(f"{self.base_url}/", wait_until="domcontentloaded", timeout=PAGE_LOAD_TIMEOUT)
            await asyncio.sleep(10)  # Let the page fully load

            # Save cookies and get them (only if cookies_file_path is set, matching original behavior)
            if self.cookies_file_path:
                await save_cookies(self.context, self.cookies_file_path)
            # Get cookies from browser
            cookies = await self.get_cookies_dict()

            await self.get_conversations_via_api(cookies)
    
    # Create scraper instance
    scraper = TaskScraperWrapper(base_url="https://www.vinted.de", headless=True, cookies_file_path=cookies_file_path, run_logger=run_logger)
    
    try:
        # Create dummy output paths (we're saving to DB, not files)
        output_csv = "/tmp/vinted_scraper_dummy.csv"
        output_json = "/tmp/vinted_scraper_dummy.json"
        
        # Run scraper
        await scraper.scrape_all_data(output_csv, output_json)
        
        # Final progress update
        await refresh_task_run()
        if task_run.status != 'CANCELLED':
            # Use the last calculated days_fetched from progress, or fallback to days_to_fetch
            final_days_fetched = task_run.progress.get('days_fetched') if task_run.progress else days_to_fetch
            
            task_run.progress = {
                'conversations_processed': processed_count[0],
                'total_conversations': processed_count[0],
                'days_fetched': final_days_fetched,
                'completed': True,
            }
            await save_task_run()
            
    except Exception as e:
        logger.error(f"TaskRun #{task_run_id}: Scraper error - {e}", exc_info=True)
        await refresh_task_run()
        if task_run.status != 'CANCELLED':
            task_run.detail = str(e)
            await save_task_run()
        raise
    finally:
        # Cleanup browser - ensure it always happens
        try:
            logger.info(f"TaskRun #{task_run_id}: Starting cleanup...")
            await scraper.cleanup()
            logger.info(f"TaskRun #{task_run_id}: Cleanup completed successfully")
        except Exception as e:
            logger.error(f"TaskRun #{task_run_id}: Cleanup error - {e}", exc_info=True)
            # Try to force cleanup even if there was an error
            try:
                if scraper.browser:
                    await scraper.browser.close()
                if scraper.playwright:
                    await scraper.playwright.stop()
            except Exception as e2:
                logger.error(f"TaskRun #{task_run_id}: Force cleanup also failed - {e2}", exc_info=True)


def _result_indicates_already_completed(result_payload: Any, response_text: str) -> bool:
    if isinstance(result_payload, dict):
        message_code = str(result_payload.get("message_code") or "").lower()
        errors = result_payload.get("errors") or []
        if message_code == "validation_error":
            error_text = " ".join(
                str(error.get("value") if isinstance(error, dict) else error)
                for error in errors
            ).lower()
            if "can't be completed" in error_text and ("status 450" in error_text or "status 455" in error_text):
                return True

    texts: list[str] = []
    if isinstance(result_payload, dict):
        texts.extend(str(value) for value in result_payload.values() if isinstance(value, (str, int, float)))
    elif result_payload is not None:
        texts.append(str(result_payload))
    if response_text:
        texts.append(response_text)

    haystack = " ".join(texts).lower()
    return "already" in haystack and "complet" in haystack


def _extract_non_completable_status(result_payload: Any) -> Optional[int]:
    if not isinstance(result_payload, dict):
        return None

    if str(result_payload.get("message_code") or "").lower() != "validation_error":
        return None

    errors = result_payload.get("errors") or []
    for error in errors:
        value = str(error.get("value") if isinstance(error, dict) else error)
        match = re.search(r"status\s+(\d+)\s+can't be completed", value, flags=re.IGNORECASE)
        if match:
            try:
                return int(match.group(1))
            except ValueError:
                return None

    return None


def _build_vinted_completion_detail(result_payload: Dict[str, Any]) -> str:
    if result_payload.get("already_completed"):
        return "Vinted transaction was already completed."
    http_status = result_payload.get("http_status")
    if http_status:
        return f"Vinted transaction completed successfully (HTTP {http_status})."
    return "Vinted transaction completed successfully."


async def _run_vinted_purchase_completion(
    *,
    task_run_id: int,
    purchase_id: Any,
    purchase_external_id: Any,
    transaction_id: Any,
    cookies_file_path: Optional[str],
    run_logger: logging.Logger,
) -> Dict[str, Any]:
    from purchases.models import Purchases

    if not purchase_id:
        raise VintedCompletionPermanentError("Missing purchase_id in task input.")
    if not purchase_external_id:
        raise VintedCompletionPermanentError("Missing purchase_external_id in task input.")
    if not transaction_id:
        raise VintedCompletionPermanentError("Missing transaction_id in task input.")

    # Validate the purchase exists, but do not short-circuit from local state.
    await sync_to_async(Purchases.objects.get)(id=purchase_id)

    class CompletionTaskScraperWrapper(VintedScraperPlaywright):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.captured_csrf_token: Optional[str] = None
            self.captured_anon_id: Optional[str] = None

        async def complete_transaction_via_api(self, cookies: Dict[str, str]) -> Dict[str, Any]:
            try:
                result = await self.page.evaluate(
                    """
                    async ({ transactionId, csrfToken, anonId }) => {
                      const metaToken =
                        document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') ||
                        document.querySelector('meta[name="csrf_token"]')?.getAttribute('content') ||
                        null;

                      const csrfCookieMatch = document.cookie.match(/(?:^|; )[^=;]*(?:csrf|xsrf)[^=;]*=([^;]+)/i);
                      const csrfCookieToken = csrfCookieMatch ? decodeURIComponent(csrfCookieMatch[1]) : null;
                      const resolvedCsrfToken = csrfToken || metaToken || csrfCookieToken;

                      const anonMatch = document.cookie.match(/(?:^|; )anon_id=([^;]+)/);
                      const resolvedAnonId = anonId || (anonMatch ? decodeURIComponent(anonMatch[1]) : null);

                      try {
                        const response = await fetch(`/api/v2/transactions/${transactionId}/complete`, {
                          method: 'PUT',
                          credentials: 'include',
                          headers: {
                            'Accept': 'application/json, text/plain, */*,image/webp',
                            'Locale': 'en-DE',
                            ...(resolvedAnonId ? { 'X-Anon-Id': resolvedAnonId } : {}),
                            ...(resolvedCsrfToken ? { 'X-CSRF-Token': resolvedCsrfToken } : {}),
                          },
                        });

                        const text = await response.text();
                        let data = null;
                        try {
                          data = JSON.parse(text);
                        } catch (error) {
                          data = null;
                        }

                        return {
                          ok: response.ok,
                          status: response.status,
                          text,
                          data,
                          csrfTokenPresent: Boolean(resolvedCsrfToken),
                          anonIdPresent: Boolean(resolvedAnonId),
                          pageUrl: window.location.href,
                        };
                      } catch (error) {
                        return {
                          ok: false,
                          status: null,
                          text: '',
                          data: null,
                          error: String(error),
                          csrfTokenPresent: Boolean(resolvedCsrfToken),
                          anonIdPresent: Boolean(resolvedAnonId),
                          pageUrl: window.location.href,
                        };
                      }
                    }
                    """,
                    {
                        "transactionId": str(transaction_id),
                        "csrfToken": self.captured_csrf_token,
                        "anonId": self.captured_anon_id or cookies.get("anon_id"),
                    },
                )

                if self.cookies_file_path:
                    await save_cookies(self.context, self.cookies_file_path)

                return result
            except Exception as exc:
                return {
                    "ok": False,
                    "status": None,
                    "text": "",
                    "data": None,
                    "error": str(exc),
                    "csrfTokenPresent": False,
                    "anonIdPresent": bool(cookies.get("anon_id")),
                    "pageUrl": self.page.url if self.page else None,
                }

        async def scrape_all_data(self, output_csv: str, output_json: str):
            self.logger.info("\n" + "=" * 80)
            self.logger.info("🚀 VINTED DATA SCRAPER")
            self.logger.info("=" * 80)
            self.logger.info(f"📋 Configuration:")
            self.logger.info(f"   Base URL: {self.base_url}")
            self.logger.info(f"   Output CSV: {output_csv}")
            self.logger.info(f"   Output JSON: {output_json}")
            self.logger.info(f"   Cookies file: {self.cookies_file_path or 'None (not using cookies)'}")
            self.logger.info("=" * 80)

            await self.setup_browser()

            self.output_csv = output_csv
            self.output_json = output_json

            if not await self.login():
                self.logger.warning("❌ Failed to login. Exiting.")
                return

            def capture_request_auth_headers(request):
                headers = request.headers
                csrf_token = headers.get("x-csrf-token")
                anon_id = headers.get("x-anon-id")

                if csrf_token and not self.captured_csrf_token:
                    self.captured_csrf_token = csrf_token
                if anon_id and not self.captured_anon_id:
                    self.captured_anon_id = anon_id

            self.page.on("request", capture_request_auth_headers)

            await self.page.goto(
                f"{self.base_url}/inbox/{purchase_external_id}?source=inbox",
                wait_until="domcontentloaded",
                timeout=PAGE_LOAD_TIMEOUT,
            )
            await asyncio.sleep(10)

            if self.cookies_file_path:
                await save_cookies(self.context, self.cookies_file_path)

            cookies = await self.get_cookies_dict()
            self.logger.info(
                "TaskRun #%s: Captured inbox auth headers csrf_token=%s anon_id=%s",
                task_run_id,
                bool(self.captured_csrf_token),
                bool(self.captured_anon_id or cookies.get("anon_id")),
            )
            return await self.complete_transaction_via_api(cookies)

    scraper = CompletionTaskScraperWrapper(
        base_url="https://www.vinted.de",
        headless=True,
        cookies_file_path=cookies_file_path,
        run_logger=run_logger,
    )

    try:
        output_csv = "/tmp/vinted_completion_dummy.csv"
        output_json = "/tmp/vinted_completion_dummy.json"
        result = await scraper.scrape_all_data(output_csv, output_json)

        if not result:
            raise VintedCompletionPermanentError("Vinted login failed or session expired.")

        if result.get("error"):
            raise VintedCompletionRetryableError(
                f"Vinted completion request failed before receiving a response: {result['error']}"
            )

        response_status = result.get("status")
        response_data = result.get("data")
        response_text = result.get("text", "")
        response_payload = response_data if response_data is not None else response_text
        response_preview = (
            json.dumps(response_data, ensure_ascii=False)
            if response_data is not None
            else response_text
        )

        run_logger.info(
            "TaskRun #%s: Vinted completion raw response status=%s csrf_token_present=%s body=%s",
            task_run_id,
            response_status,
            result.get("csrfTokenPresent"),
            response_preview[:2000],
        )

        if response_status and 200 <= response_status < 300:
            if not response_data or str(response_data.get("code", "0")) == "0":
                return {
                    "purchase_id": purchase_id,
                    "purchase_external_id": str(purchase_external_id),
                    "transaction_id": str(transaction_id),
                    "http_status": response_status,
                    "response": response_data or response_text,
                    "already_completed": False,
                }

        if _result_indicates_already_completed(response_data, response_text):
            return {
                "purchase_id": purchase_id,
                "purchase_external_id": str(purchase_external_id),
                "transaction_id": str(transaction_id),
                "http_status": response_status,
                "response": response_data or response_text,
                "already_completed": True,
                "completed_via": "remote_response",
            }

        non_completable_status = _extract_non_completable_status(response_data)
        if non_completable_status in {210, 230}:
            raise VintedCompletionPermanentError(
                f"Vinted transaction is not ready to be completed yet (status {non_completable_status}). "
                f"Raw response: {response_payload}"
            )

        if response_status in {429, 500, 502, 503, 504}:
            raise VintedCompletionRetryableError(
                f"Vinted completion temporary failure ({response_status}): {response_text[:500]}"
            )

        if response_status in {401, 403}:
            raise VintedCompletionPermanentError(
                f"Vinted completion failed ({response_status}): {response_payload}"
            )

        raise VintedCompletionPermanentError(
            f"Vinted completion failed ({response_status}): {response_payload}"
        )
    finally:
        await scraper.cleanup()


@shared_task(bind=True, max_retries=3, name="tasks.tasks.complete_vinted_purchase_task")
def complete_vinted_purchase_task(self, task_run_id: int):
    """Complete a single Vinted purchase in the background."""
    from .models import TaskRun
    from purchases.models import Purchases

    task_run = None
    try:
        close_old_connections()
        task_run = TaskRun.objects.select_related('task').get(id=task_run_id)
        task = task_run.task

        task_run.status = 'RUNNING'
        task_run.started_at = task_run.started_at or timezone.now()
        task_run.detail = 'Completing Vinted purchase.'
        close_old_connections()
        task_run.save(update_fields=['status', 'started_at', 'detail'])

        run_logger = initialize_task_run_logger(
            task_run,
            f"TaskRun #{task_run_id}: Starting Vinted purchase completion",
        )

        input_data = task_run.input_data or {}
        task_run.progress = {
            'purchase_id': input_data.get('purchase_id'),
            'purchase_external_id': input_data.get('purchase_external_id'),
            'transaction_id': input_data.get('transaction_id'),
            'attempt': self.request.retries + 1,
        }
        close_old_connections()
        task_run.save(update_fields=['progress'])

        cookies_file_path = task.cookies_file.path if task.cookies_file else None
        result = asyncio.run(
            _run_vinted_purchase_completion(
                task_run_id=task_run_id,
                purchase_id=input_data.get('purchase_id'),
                purchase_external_id=input_data.get('purchase_external_id'),
                transaction_id=input_data.get('transaction_id'),
                cookies_file_path=cookies_file_path,
                run_logger=run_logger,
            )
        )

        close_old_connections()
        purchase = Purchases.objects.get(id=input_data.get('purchase_id'))
        platform_data = purchase.platform_data or {}
        platform_data['transaction_completed'] = True
        purchase.platform_data = platform_data
        purchase.save()

        close_old_connections()
        task_run.refresh_from_db()
        if task_run.status != 'CANCELLED':
            task_run.status = 'SUCCESS'
            task_run.finished_at = timezone.now()
            task_run.detail = _build_vinted_completion_detail(result)
            task_run.progress = result
            close_old_connections()
            task_run.save(update_fields=['status', 'finished_at', 'detail', 'progress'])
            run_logger.info("TaskRun #%s: Vinted purchase completion succeeded", task_run_id)

        return result

    except VintedCompletionRetryableError as exc:
        countdown = min(RETRY_BACKOFF_MAX_SEC, RETRY_BACKOFF_BASE_SEC * (2 ** self.request.retries))
        if task_run and self.request.retries < self.max_retries:
            task_run.status = 'PENDING'
            task_run.detail = f"Retrying: {exc}"
            close_old_connections()
            task_run.save(update_fields=['status', 'detail'])
            raise self.retry(exc=exc, countdown=countdown)

        if task_run:
            task_run.status = 'FAILURE'
            task_run.detail = str(exc)
            task_run.finished_at = timezone.now()
            close_old_connections()
            task_run.save(update_fields=['status', 'detail', 'finished_at'])
        raise
    except VintedCompletionPermanentError as exc:
        if task_run:
            task_run.status = 'FAILURE'
            task_run.detail = str(exc)
            task_run.finished_at = timezone.now()
            close_old_connections()
            task_run.save(update_fields=['status', 'detail', 'finished_at'])
        raise
    except TaskRun.DoesNotExist:
        logger.error("TaskRun #%s: TaskRun not found", task_run_id)
        raise
    except Exception as exc:
        logger.error("TaskRun #%s: Vinted purchase completion failed - %s", task_run_id, exc, exc_info=True)
        if task_run:
            task_run.status = 'FAILURE'
            task_run.detail = str(exc)
            task_run.finished_at = timezone.now()
            close_old_connections()
            task_run.save(update_fields=['status', 'detail', 'finished_at'])
        raise
    finally:
        try:
            if task_run:
                close_old_connections()
                task_run.refresh_from_db()
                if task_run.status == 'RUNNING':
                    task_run.status = 'FAILURE'
                    task_run.detail = "Task stopped unexpectedly"
                    task_run.finished_at = timezone.now()
                    close_old_connections()
                    task_run.save(update_fields=['status', 'detail', 'finished_at'])
        except Exception as exc:
            logger.error("TaskRun #%s: Error in completion finally block - %s", task_run_id, exc)
