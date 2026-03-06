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
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from celery import shared_task
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


# ============================================================================
# VINTED SCRAPER CLASS
# ============================================================================

class VintedScraperPlaywright:
    def __init__(self, base_url: str = "https://www.vinted.de", headless: bool = False, cookies_file_path: Optional[str] = None):
        self.base_url = base_url
        self.headless = headless
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None
        self.output_csv = None
        self.output_json = None
        self.cookies_file_path = cookies_file_path  # Store as instance variable (like COOKIES_FILE in original)
    
    async def setup_browser(self):
        """Initialize Playwright browser."""
        logger.info("Setting up browser...")
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
        logger.info("✓ Browser ready")
    
    async def login(self) -> bool:
        """Handle login process - load cookies or wait for manual login."""
        logger.info("\n" + "=" * 80)
        logger.info("🔐 LOGIN PROCESS")
        logger.info("-" * 80)
        
        # Try to load existing cookies (only if cookies_file_path is provided)
        cookies_loaded = False
        if self.cookies_file_path:
            cookies_loaded = await load_cookies(self.context, self.cookies_file_path)
        
        if cookies_loaded:
            logger.info("✅ Cookies loaded. Checking session...")
            await self.page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=PAGE_LOAD_TIMEOUT)
            await asyncio.sleep(5)
            
            if await is_logged_in(self.page):
                logger.info("✅ Session is valid.")
                return True
            else:
                logger.warning("⚠️  Session expired.")
                # Try automatic login if credentials provided
                if EMAIL and PASSWORD:
                    if await self.auto_login(EMAIL, PASSWORD):
                        if self.cookies_file_path:
                            await save_cookies(self.context, self.cookies_file_path)
                        return True
                    else:
                        logger.warning("⚠️  Falling back to manual login...")
                
                # Fall back to manual login
                logger.warning("⚠️  Session expired. Please log in manually.")
                if not await wait_for_manual_login(self.page, LOGIN_TIMEOUT):
                    logger.warning("❌ Login failed. Exiting.")
                    return False
                if self.cookies_file_path:
                    await save_cookies(self.context, self.cookies_file_path)

                if not await wait_for_manual_login(self.page, LOGIN_TIMEOUT):
                    logger.warning("❌ Login failed. Exiting.")
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
                    logger.warning("⚠️  Falling back to manual login...")
            
            # Fall back to manual login
            await self.page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=PAGE_LOAD_TIMEOUT)
            await asyncio.sleep(5)
            
            if not await wait_for_manual_login(self.page, LOGIN_TIMEOUT):
                logger.warning("❌ Login failed. Exiting.")
                return False
            if self.cookies_file_path:
                await save_cookies(self.context, self.cookies_file_path)
        
        logger.info("✅ Login successful!")
        return True
    
    async def refresh_cookies(self) -> Dict[str, str]:
        """Refresh cookies from browser context."""
        logger.info("🔄 Refreshing cookies...")
        
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
        
        logger.info("✓ Cookies refreshed")
        return cookies

    async def get_cookies_dict(self) -> Dict[str, str]:
        """Get browser cookies as dictionary."""
        cookies = {}
        for cookie in await self.context.cookies():
            cookies[cookie['name']] = cookie.get('value', None)
        
        return cookies
    
    async def api_request(self, session: aiohttp.ClientSession, url: str, method: str = "GET"):
        """
        Returns (data, new_session) tuple.
        If cookies were refreshed, new_session is a new aiohttp session.
        """
        async with session.request(method, url) as response:
            if response.status == 429:
                try:
                    error_data = await response.json()
                    raise Exception(f"Rate limit: {json.dumps(error_data)}")
                except:
                    raise Exception("Rate limit (429)")

            if response.status in (400, 401):
                logger.warning(f"Auth error {response.status} on {url} → refreshing cookies...")
                await session.close()

                try:
                    new_cookies = await self.refresh_cookies()
                    new_session = aiohttp.ClientSession(
                        headers={
                            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                            "Accept": "application/json, text/plain, */*",
                            "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7",
                            "Referer": f"{self.base_url}/inbox",
                            "Origin": self.base_url,
                        },
                        cookies=new_cookies
                    )
                    logger.info("Retrying request with fresh cookies...")
                    # Retry once with new session
                    async with new_session.request(method, url) as retry_resp:
                        retry_resp.raise_for_status()
                        return await retry_resp.json(), new_session
                except Exception as e:
                    logger.error(f"Failed even after refresh: {e}")
                    raise

            # Normal success or other error
            response.raise_for_status()
            return await response.json(), session  # same session
    
    async def get_conversation_details(self, conversation_id: int, session: aiohttp.ClientSession) -> Optional[Dict]:
        """Fetch conversation details to get transaction ID."""
        await asyncio.sleep(1)
        url = f"{self.base_url}/api/v2/conversations/{conversation_id}"
        return await self.api_request(session, url)
    
    async def get_transaction_details(self, transaction_id: int, session: aiohttp.ClientSession) -> Optional[Dict]:
        """Fetch transaction details."""
        await asyncio.sleep(1)
        url = f"{self.base_url}/api/v2/transactions/{transaction_id}"
        return await self.api_request(session, url)

    async def get_refund_details(self, transaction_id: int, session: aiohttp.ClientSession) -> Optional[Dict]:
        """Fetch transaction details."""
        await asyncio.sleep(1)
        url = f"{self.base_url}/api/v2/transactions/{transaction_id}/refund"
        return await self.api_request(session, url)
    
    async def get_escrow_order_details(self, transaction_id: int, session: aiohttp.ClientSession) -> Optional[Dict]:
        """Fetch escrow order details for detailed pricing breakdown."""
        await asyncio.sleep(1)
        url = f"{self.base_url}/api/v2/escrow_orders/{transaction_id}"
        return await self.api_request(session, url)

    async def get_tracking_journey(self, transaction_id: int, session: aiohttp.ClientSession) -> Optional[Dict]:
        """Fetch tracking journey summary for a transaction."""
        await asyncio.sleep(1)
        url = f"{self.base_url}/api/v2/transactions/{transaction_id}/shipment/journey_summary"
        return await self.api_request(session, url)

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
            logger.warning("🔐 Attempting automatic login...")
            
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
                        logger.info(f"   Clicking: {option_text}...")
                        await locator.click()
                        await asyncio.sleep(1)
            except:
                pass  # Popups didn't appear or already handled

            # Fill in email/username
            logger.info("   Filling email...")
            await self.page.fill('input[name="username"]', email)
            await asyncio.sleep(0.5)
            
            # Fill in password
            logger.info("   Filling password...")
            await self.page.fill('input[name="password"]', password)
            await asyncio.sleep(0.5)
            
            # Click submit button
            logger.info("   Clicking submit button...")
            await self.page.click('button[type="submit"]')
            
            # Wait for potential captcha or login completion
            logger.info("⏳ Waiting for login to complete...")
            logger.info("   (If captcha appears, please solve it - 60 seconds available)")
            
            # Monitor login status for 60 seconds
            start_time = asyncio.get_event_loop().time()
            timeout_seconds = 60
            check_interval = 2  # Check every 2 seconds
            
            while (asyncio.get_event_loop().time() - start_time) < timeout_seconds:
                await asyncio.sleep(check_interval)
                
                current_url = self.page.url
                
                # Check if successfully logged in
                if await is_logged_in(self.page):
                    logger.info("✅ Automatic login successful!")
                    return True
                
                # Check if still on login page (waiting for captcha or error)
                if LOGIN_URL_FRAGMENT in current_url:
                    elapsed = int(asyncio.get_event_loop().time() - start_time)
                    remaining = timeout_seconds - elapsed
                    logger.info(f"   ⏳ Still on login page... ({remaining}s remaining)")
                else:
                    # Navigated somewhere else, check status
                    logger.info(f"   Current URL: {current_url}")
            
            # Timeout reached
            logger.warning("❌ Login timeout reached (60 seconds)")
            
            # Final check
            if await is_logged_in(self.page):
                logger.info("✅ Login successful (completed just in time!)")
                return True
            else:
                logger.warning("❌ Automatic login failed")
                return False
                
        except Exception as e:
            logger.warning(f"❌ Auto-login error: {e}")
            import traceback
            traceback.print_exc()
            return False

    async def process_conversation(self, session, conv):
        conv_id = conv.get('id')
        
        # Step 1: Get conversation details
        success, conv_resp, error = await retry_with_backoff_async(
            lambda: self.get_conversation_details(conv_id, session)
        )
        
        if not success:
            logger.warning(f"⚠️  Skipping conversation {conv_id} - Failed to get conversation details: {error}")
            return None, session
        
        conversation_data, session = conv_resp

        if not conversation_data:
            logger.warning(f"⚠️  Skipping conversation {conv_id} - Failed to get conversation details: {error}")
            return None, session
        
        conversation_data['purchase_amount'] = conv.get('purchase_amount')
        conversation_data['purchase_currency'] = conv.get('purchase_currency')
        conversation_data['purchase_date'] = conv.get('purchase_date')
        
        # Step 2: Extract transaction ID
        conversation = conversation_data.get("conversation", {})
        transaction_info = conversation.get("transaction", {})
        transaction_id = transaction_info.get("id")
        
        if not transaction_id:
            logger.warning(f"⚠️  No transaction ID found for conversation {conv_id}")
            return None, session
        
        logger.info(f"   → Transaction ID: {transaction_id}")
        
        # Step 3: Get transaction details
        success, trans_resp, error = await retry_with_backoff_async(
            lambda: self.get_transaction_details(transaction_id, session)
        )

        if not success:
            logger.warning(f"⚠️  Skipping conversation {conv_id} - Failed to get transaction details: {error}")
            return None, session
        
        transaction_data, session = trans_resp

        if not transaction_data:
            logger.warning(f"⚠️  Skipping conversation {conv_id} - Failed to get transaction details: {error}")
            return None, session

        status_title = transaction_data.get("transaction", {}).get('status_title', '').strip()
        logger.info(f"   → Transaction status: {status_title}")
        # if status_title not in COMPLETED_STATUSES:
        #     logger.warning(f"⚠️  Skipping conversation (transaction status: {status_title}) - Incomplete purchase")
        #     return None, session

        # Step 4: Get tracking journey
        success, tracking_resp, error = await retry_with_backoff_async(
            lambda: self.get_tracking_journey(transaction_id, session)
        )

        tracking_data = None
        if not success:
            logger.warning(f"⚠️  Could not fetch tracking journey: {error}")

        if tracking_resp:
            tracking_data, session = tracking_resp
        

        refund_data = {}
        if not status_title:
            # fetching refund data
            success, refund_resp, error = await retry_with_backoff_async(
                lambda: self.get_refund_details(transaction_id, session)
            )
            
            if not success:
                logger.warning(f"⚠️  Failed to get refund details: {error}")

            if refund_resp:
                refund_data, session = refund_resp

        # Step 5: Get escrow order details for detailed pricing
        success, escrow_resp, error = await retry_with_backoff_async(
            lambda: self.get_escrow_order_details(transaction_id, session)
        )
        
        escrow_data = None
        if not success:
            logger.warning(f"⚠️  Could not fetch escrow order details: {error}")
        else:
            if escrow_resp:
                escrow_data, session = escrow_resp

        extracted_data = await self.extract_purchase_data(
            conversation_data, transaction_data, tracking_data, refund_data, escrow_data, conv_id
        )
        
        # Print full conversation details with indentation
        if extracted_data:
            logger.info("\n" + "=" * 80)
            logger.info(f"📋 FULL CONVERSATION DETAILS (ID: {conv_id})")
            logger.info("=" * 80)
            logger.info(json.dumps(extracted_data, indent=2, ensure_ascii=False, default=str))
            logger.info("=" * 80 + "\n")
        
        return extracted_data, session

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
            
            # Normalize status
            if status_title:
                if status_title == "Order completed!":
                    status_title = "Completed"
            else:
                status_title = "Refunded"
            
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
                
                # fetching item photos
                photos = []
                for photo in item.get('photos', []):
                    photos.append(photo.get("full_size_url") or photo.get("url"))
                
                price_obj = item.get('price', {})
                item_price_val = price_obj.get('amount')
                item_currency = price_obj.get('currency_code')
                
                items.append({
                    'title': item_title,
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
            logger.info(f"   → Tracking status: {tracking_status}")

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
            logger.warning(f"Error extracting data for conv {conversation_id}: {e}")
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
                500: "uncompleted",
                430: "cancelled",
                510: "cancelled",
                520: "cancelled",
            }
            if transaction_status in status_map:
                return status_map[transaction_status]
        
        # Map status titles (case-insensitive)
        if status_title:
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
        
        # FALLBACK: Match status field behavior - if status_title is empty, assume refunded
        if not status_title:
            return "refunded"
        
        return None

    async def cleanup(self):
        """Close browser and cleanup."""
        logger.info("\nCleaning up browser resources...")
        
        # Close context (closes all pages)
        if self.context:
            try:
                await self.context.close()
                logger.info("✓ Browser context closed")
            except Exception as e:
                logger.warning(f"⚠️  Error closing context: {e}")
            finally:
                self.context = None
        
        # Close browser
        if self.browser:
            try:
                await self.browser.close()
                logger.info("✓ Browser closed")
            except Exception as e:
                logger.warning(f"⚠️  Error closing browser: {e}")
            finally:
                self.browser = None
        
        # Stop playwright
        if self.playwright:
            try:
                await self.playwright.stop()
                logger.info("✓ Playwright stopped")
            except Exception as e:
                logger.warning(f"⚠️  Error stopping playwright: {e}")
            finally:
                self.playwright = None
        
        logger.info("✓ Cleanup complete")

@shared_task(bind=True)
def scheduled_vinted_scraper(self):
    """
    Scheduled wrapper for the Vinted scraper (called by Celery Beat).
    Creates a TaskRun and delegates to fetch_vinted_conversations_task.
    Skips if a scraper is already running.
    """
    from .models import Task, TaskRun

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
    )
    logger.info(f"Scheduled scraper: Created TaskRun #{task_run.id}")

    # Dispatch the actual scraper task
    fetch_vinted_conversations_task.delay(task_run_id=task_run.id)


@shared_task(bind=True)
def fetch_vinted_conversations_task(self, task_run_id: int):
    """
    Celery task for fetching Vinted conversations.
    Wraps the existing Vinted scraper and integrates with TaskRun.
    
    Args:
        task_run_id: ID of the TaskRun instance to track progress
    """
    try:
        from .models import TaskRun
        from apps.purchases.models import Purchases
        from apps.purchases.adapters import get_adapter
        
        # Get TaskRun and Task instances
        task_run = TaskRun.objects.get(id=task_run_id)
        task = task_run.task
        
        # Update status to RUNNING
        task_run.status = 'RUNNING'
        task_run.started_at = timezone.now()
        task_run.save()
        
        logger.info(f"TaskRun #{task_run_id}: Starting Vinted conversation scraper")
        
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
        task_run.save()
        
        # Run async scraper
        asyncio.run(
            _run_vinted_scraper(
                task_run_id=task_run_id,
                cookies_file_path=cookies_file_path,
                days_to_fetch=days_to_fetch,
                max_conversations=max_conversations,
            )
        )
        
        # Update status to SUCCESS
        task_run.refresh_from_db()
        if task_run.status != 'CANCELLED':
            task_run.status = 'SUCCESS'
            task_run.finished_at = timezone.now()
            task_run.save()
            logger.info(f"TaskRun #{task_run_id}: Completed successfully")
        
    except TaskRun.DoesNotExist:
        logger.error(f"TaskRun #{task_run_id}: TaskRun not found")
        raise
    except Exception as e:
        logger.error(f"TaskRun #{task_run_id}: Failed - {e}", exc_info=True)
        try:
            task_run.refresh_from_db()
            if task_run.status != 'CANCELLED':
                task_run.status = 'FAILURE'
                task_run.error_message = str(e)
                task_run.finished_at = timezone.now()
                task_run.save()
        except Exception:
            pass
        raise


async def _run_vinted_scraper(
    task_run_id: int,
    cookies_file_path: Optional[str],
    days_to_fetch: Optional[int],
    max_conversations: Optional[int] = None,
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
    from apps.purchases.models import Purchases
    from apps.purchases.adapters import get_adapter
    
    # Get TaskRun for progress updates (using async ORM method)
    task_run = await TaskRun.objects.aget(id=task_run_id)
    
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
        
        def __init__(self, base_url: str = "https://www.vinted.de", headless: bool = False, cookies_file_path: Optional[str] = None):
            super().__init__(base_url=base_url, headless=headless, cookies_file_path=cookies_file_path)
        
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
                    session = aiohttp.ClientSession(headers=session_headers, cookies=cookies)
                else:
                    session = aiohttp.ClientSession(headers=session_headers)
                
                now = datetime.now()
                today_start = datetime(now.year, now.month, now.day, 0, 0, 0)
                
                if days_to_fetch is None:
                    # Fetch all conversations - set cutoff_date to a very old date
                    cutoff_date = datetime(1970, 1, 1)
                    logger.info(f"TaskRun #{task_run_id}: Fetching all orders (no date limit)")
                else:
                    # If days_to_fetch is 1, fetch today only (cutoff = today at 00:00:00)
                    # If days_to_fetch is 2, fetch today and yesterday (cutoff = yesterday at 00:00:00)
                    # So cutoff = today - (days_to_fetch - 1) days at 00:00:00
                    cutoff_date = today_start - timedelta(days=days_to_fetch - 1)
                    logger.info(f"TaskRun #{task_run_id}: Fetching orders from last {days_to_fetch} days (cutoff: {cutoff_date.strftime('%Y-%m-%d %H:%M:%S')})")
                
                page = 1
                PER_PAGE = 50
                REFRESH_COOKIES_AFTER_N_CONV = 100
                ind = 0
                # Track the oldest conversation date to calculate actual days fetched
                oldest_conv_date = None
                
                while True:
                    # Check for cancellation
                    await task_run.arefresh_from_db()
                    if task_run.status == 'CANCELLED':
                        logger.info(f"TaskRun #{task_run_id}: Cancelled at page {page}")
                        await session.close()
                        return
                    
                    try:
                        await asyncio.sleep(1)
                        
                        url = f"{self.base_url}/api/v2/my_orders?type=purchased&status=completed&page={page}&per_page={PER_PAGE}"
                        data, session = await self.api_request(session, url)
                        
                        if not data:
                            if page == 1:
                                logger.warning(f"TaskRun #{task_run_id}: Failed to fetch orders. API authentication may have failed.")
                            break
                        
                        conversations = data.get("my_orders", [])
                        
                        if not conversations:
                            logger.info(f"TaskRun #{task_run_id}: No more orders on page {page}")
                            break
                        
                        logger.info(f"TaskRun #{task_run_id}: Page {page}: Found {len(conversations)} conversations")
                        
                        # Update progress with current page (before processing conversations)
                        current_page[0] = page
                        task_run.progress = {
                            'conversations_processed': processed_count[0],
                            'total_conversations': None,
                            'days_fetched': calculate_days_fetched(oldest_conv_date, days_to_fetch, now),
                            'current_page': page,
                        }
                        await task_run.asave()
                        
                        for conv in conversations:
                            # Check for cancellation
                            await task_run.arefresh_from_db()
                            if task_run.status == 'CANCELLED':
                                logger.info(f"TaskRun #{task_run_id}: Cancelled at conversation {ind + 1}")
                                await session.close()
                                return
                            
                            ind += 1
                            
                            # Session refreshing (from original code)
                            if ind % REFRESH_COOKIES_AFTER_N_CONV == 0:
                                await session.close()
                                cookies = await self.refresh_cookies()
                                
                                session = aiohttp.ClientSession(
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
                                    "purchase_date": purchase_date
                                }
                                
                                logger.info(f"TaskRun #{task_run_id}: [{ind}] Processing conversation ID {conv_id}")
                                
                                # Process conversation (this calls the original method)
                                extracted_data, session = await self.process_conversation(session, conv_data)
                                
                                if extracted_data:
                                    updated_at_str = extracted_data.get("updated_at", "")
                                    if updated_at_str:
                                        try:
                                            conv_updated_at = datetime.strptime(f"{updated_at_str[:19]}", "%Y-%m-%dT%H:%M:%S")
                                            logger.info(f"TaskRun #{task_run_id}:   → Updated at: {conv_updated_at}")
                                            
                                            # Track oldest conversation date for days progress calculation
                                            if oldest_conv_date is None or conv_updated_at < oldest_conv_date:
                                                oldest_conv_date = conv_updated_at
                                            
                                            # Check if conversation is older than cutoff date
                                            # Compare dates at day level (ignore time)
                                            conv_date_start = datetime(conv_updated_at.year, conv_updated_at.month, conv_updated_at.day, 0, 0, 0)
                                            if days_to_fetch is not None and conv_date_start < cutoff_date:
                                                ind -= 1
                                                logger.info(
                                                    f"TaskRun #{task_run_id}: Reached conversations older than "
                                                    f"{days_to_fetch} days (updated_at: {updated_at_str[:19]}). Stopping."
                                                )
                                                await session.close()
                                                return
                                        except ValueError:
                                            pass  # Invalid date format, continue
                                    
                                    # Save to Purchases model
                                    try:
                                        normalized = adapter.normalize(extracted_data)
                                        
                                        # Create or update Purchases instance
                                        purchase, created = await Purchases.objects.aupdate_or_create(
                                            platform='vinted',
                                            external_id=normalized['external_id'],
                                            defaults=normalized
                                        )
                                        
                                        action = "Created" if created else "Updated"
                                        logger.info(
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
                                        await task_run.asave()
                                        
                                    except Exception as e:
                                        logger.error(
                                            f"TaskRun #{task_run_id}: Failed to save conversation "
                                            f"{conv_id}: {e}",
                                            exc_info=True
                                        )
                                        # Continue processing other conversations
                                        continue
                                    
                                    # Check max conversations limit
                                    if max_conversations and processed_count[0] >= max_conversations:
                                        logger.info(
                                            f"TaskRun #{task_run_id}: Reached max conversations limit "
                                            f"({max_conversations}). Stopping."
                                        )
                                        await session.close()
                                        return
                        
                        # Check pagination
                        pagination = data.get("pagination", {})
                        if int(pagination.get("total_pages", 1)) == page:
                            logger.info(f"TaskRun #{task_run_id}: Reached last page!")
                            break
                        
                        page += 1
                        continue
                    
                    except Exception as e:
                        logger.error(f"TaskRun #{task_run_id}: Error fetching orders on page {page}: {e}", exc_info=True)
                        break
                
                # Close aiohttp session
                await session.close()
                
                logger.info(f"TaskRun #{task_run_id}: Scraping complete! Total conversations processed: {processed_count[0]}")
                
            except Exception as e:
                logger.error(f"TaskRun #{task_run_id}: Error in get_conversations_via_api: {e}", exc_info=True)
                raise
        
        async def save_to_file(self, output_csv_path, output_json_path, all_data):
            """Override to prevent file saving - we save to Purchases model instead."""
            # No-op: Do not save to files
            pass
        
        async def scrape_all_data(self, output_csv, output_json):
            """Override scrape_all_data to match original logic exactly."""
            logger.info("\n" + "=" * 80)
            logger.info("🚀 VINTED DATA SCRAPER")
            logger.info("=" * 80)
            logger.info(f"📋 Configuration:")
            logger.info(f"   Base URL: {self.base_url}")
            logger.info(f"   Output CSV: {output_csv}")
            logger.info(f"   Output JSON: {output_json}")
            logger.info(f"   Cookies file: {self.cookies_file_path or 'None (not using cookies)'}")
            logger.info("=" * 80)
            
            await self.setup_browser()
            
            self.output_csv = output_csv
            self.output_json = output_json

            if not await self.login():
                logger.warning("❌ Failed to login. Exiting.")
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
    scraper = TaskScraperWrapper(base_url="https://www.vinted.de", headless=True, cookies_file_path=cookies_file_path)
    
    try:
        # Create dummy output paths (we're saving to DB, not files)
        output_csv = "/tmp/vinted_scraper_dummy.csv"
        output_json = "/tmp/vinted_scraper_dummy.json"
        
        # Run scraper
        await scraper.scrape_all_data(output_csv, output_json)
        
        # Final progress update
        await task_run.arefresh_from_db()
        if task_run.status != 'CANCELLED':
            # Use the last calculated days_fetched from progress, or fallback to days_to_fetch
            final_days_fetched = task_run.progress.get('days_fetched') if task_run.progress else days_to_fetch
            
            task_run.progress = {
                'conversations_processed': processed_count[0],
                'total_conversations': processed_count[0],
                'days_fetched': final_days_fetched,
                'completed': True,
            }
            await task_run.asave()
            
    except Exception as e:
        logger.error(f"TaskRun #{task_run_id}: Scraper error - {e}", exc_info=True)
        await task_run.arefresh_from_db()
        if task_run.status != 'CANCELLED':
            task_run.error_message = str(e)
            await task_run.asave()
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
