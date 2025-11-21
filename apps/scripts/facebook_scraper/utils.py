import os
import re
import json
import asyncio
from pathlib import Path
from urllib.parse import quote
from typing import Dict, List, Optional
from datetime import datetime, timezone
from playwright.async_api import async_playwright, Browser, BrowserContext, Page
from django.conf import settings


def get_absolute_path(file_field) -> str | None:
    """
    Convert a Django FileField (e.g. Script.cookies_file) to an absolute filesystem path.
    Returns None if the file is not uploaded.
    """
    if not file_field:
        return None
    return os.path.join(settings.MEDIA_ROOT, file_field.name)


async def save_cookies(context, path: str) -> None:
    """Save browser cookies to a JSON file."""
    cookies = await context.cookies()
    Path(path).write_text(json.dumps(cookies, indent=2))
    print(f"✅ Cookies saved to {path}")


async def load_cookies(context: BrowserContext, file_field) -> bool:
    """
    Load cookies from Script.cookies_file (FileField).
    Returns True if cookies were loaded, False otherwise.
    """
    path = get_absolute_path(file_field)
    if not path or not Path(path).exists():
        print(f"No cookies file found at {path}")
        return False

    try:
        cookies = json.loads(Path(path).read_text(encoding="utf-8"))
        await context.add_cookies(cookies)
        print(f"Cookies loaded from {path}")
        return True
    except Exception as e:
        print(f"Failed to load cookies: {e}")
        return False


def create_browser_args() -> List[str]:
    """Return browser launch arguments for stealth mode."""
    return [
        "--no-sandbox",
        "--disable-setuid-sandbox",
        "--disable-dev-shm-usage",
        "--disable-gpu",
        "--shm-size=2gb",
        "--disable-infobars",
        "--disable-extensions",
        "--disable-background-timer-throttling",
        "--disable-renderer-backgrounding",
        "--disable-backgrounding-occluded-windows",
        "--disable-blink-features=AutomationControlled",
    ]

def build_search_url(city: str, query: str, days: str) -> str:
    """Build Facebook Marketplace search URL with quoted query."""
    quoted_query = quote(query)
    return (
        f"https://www.facebook.com/marketplace/{city.lower()}/search"
        f"?daysSinceListed={days}"
        f"&sortBy=best_match"
        f"&query={quoted_query}"
    )


async def scroll_to_bottom(page) -> None:
    """Scroll page to bottom."""
    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    await asyncio.sleep(1.5)


import re

async def is_logged_in(page: Page) -> bool:
    """
    Check if user is logged in to Facebook by detecting common login indicators.
    Handles multiple languages and case-insensitive partial text matches.
    """
    try:
        patterns = [
            r"see more on facebook",
            r"bei facebook anmelden",
            r"log\s*in",
            r"sign\s*in",
            r"anmelden",
            r"e-mail-adresse oder telefonnummer",
            r"email",
        ]

        # Check input fields
        if await page.locator('input[name="email"]').is_visible() or \
           await page.locator('input[name="pass"]').is_visible():
            return False

        # Check for login-related texts anywhere on page
        for pattern in patterns:
            locator = page.locator("*", has_text=re.compile(pattern, re.I))
            if await locator.is_visible():
                return False

        return True  # No login elements found → user is logged in

    except Exception as e:
        print(f"Error in is_logged_in: {e}")
        return False
