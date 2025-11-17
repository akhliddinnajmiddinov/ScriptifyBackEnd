import os
from typing import List
from dotenv import load_dotenv

load_dotenv()

# Environment variables
HEADLESS = os.getenv('HEADLESS', 'false').lower() in ['true', '1', 'yes']
COOKIES_FILE = os.getenv("COOKIES_FILE", "fb_cookies.json")
QUERY = os.getenv("QUERY", "Canon Printer Cartridge")
LAST_N_DAYS = os.getenv("LAST_N_DAYS", "7")
LISTINGS_PER_CITY = int(os.getenv("LISTINGS_PER_CITY", "50"))
LOGIN_TIMEOUT = int(os.getenv("LOGIN_TIMEOUT", "180000"))

# Constants
PAGE_LOAD_TIMEOUT = 120000
MAX_NO_NEW_ITEMS_ATTEMPTS = 3


class RetryConfig:
    """Configuration for retry logic with exponential backoff"""
    def __init__(self):
        self.attempts = int(os.getenv('RETRY_MAX_ATTEMPTS', '3'))
        self.backoff_base_sec = float(os.getenv('RETRY_BACKOFF_BASE_SEC', '2.0'))
        self.backoff_max_sec = float(os.getenv('RETRY_BACKOFF_MAX_SEC', '60.0'))


def get_retry_config() -> RetryConfig:
    """Get retry configuration from environment or defaults"""
    return RetryConfig()