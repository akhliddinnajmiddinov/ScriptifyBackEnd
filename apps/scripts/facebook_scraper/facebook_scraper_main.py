import os
import logging
import asyncio
from datetime import datetime
from typing import Dict, Any
from playwright.async_api import async_playwright, Browser, BrowserContext, Page
from .config import (
    LAST_N_DAYS,
    QUERY,
    LISTINGS_PER_CITY,
    LOGIN_TIMEOUT,
    PAGE_LOAD_TIMEOUT,
    MAX_NO_NEW_ITEMS_ATTEMPTS,
    HEADLESS
)
from .retry_with_backoff_async import retry_with_backoff_async
from .utils import create_browser_args, build_search_url, save_cookies, load_cookies, is_logged_in
from .scraper import setup_response_handlers, scrape_city
from apps.scripts.utils import ResultWriter


class FacebookMarketplaceScraper:
    def __init__(self, run, script, input_data, logger, writer):
        cities = input_data.get('cities', [])
        if not cities:
            raise ValueError("No cities provided")
        
        query = input_data.get('query')
        if not query:
            raise ValueError("No search query provided")
        
        try:
            last_n_days = int(input_data.get('last_n_days', 5))
        except:
            last_n_days = 7
        
        try:
            listings_per_city = int(input_data.get('listings_per_city'))
        except:
            listings_per_city = LISTINGS_PER_CITY
        

        result_path = run.result_file.path
        os.makedirs(os.path.dirname(result_path), exist_ok=True)

        logger.info(f"Scraping {len(cities)} city(s): {', '.join(cities)}")


        self.cities = cities
        self.query = query
        self.last_n_days = last_n_days
        self.listings_per_city = listings_per_city
        self.run = run
        self.logger = logger
        self.writer = writer
        self.script = script
        self.seen_links: set = set()
        self.all_results = {}


    async def _async_main(self):
        self.logger.info("=" * 80)
        self.logger.info("🚀 FACEBOOK MARKETPLACE SCRAPER")
        self.logger.info("=" * 80)
        self.logger.info(f"📋 Configuration:")
        self.logger.info(f"   Query: \"{self.query}\"")
        self.logger.info(f"   Cities: {', '.join(self.cities)}")
        self.logger.info(f"   Days: {self.last_n_days}")
        self.logger.info(f"   Listings per city: {self.listings_per_city}")
        self.logger.info(f"   Cookies file: {self.run}")
        self.logger.info("=" * 80)

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=HEADLESS,
                args=create_browser_args()
            )
            context = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1280, "height": 720},
            )
            page = await context.new_page()

            # ---------- LOGIN PROCESS ----------
            # ---------- LOGIN PROCESS ----------
            self.logger.info("\n🔐 LOGIN PROCESS")
            self.logger.info("-" * 80)

            # Build a search URL for login check (using first city)
            login_check_url = build_search_url(self.cities[0], self.query, self.last_n_days)
            cookies_loaded = await load_cookies(context, self.script.cookies_file)

            if cookies_loaded:
                self.logger.info("✅ Cookies loaded. Checking session...")
                await page.goto(login_check_url, wait_until="domcontentloaded", timeout=PAGE_LOAD_TIMEOUT)
                await asyncio.sleep(10)  # Give page time to load
                
                if await is_logged_in(page):
                    self.logger.info("✅ Session is valid.")
                else:
                    self.logger.info("⚠️  Cookies expired. Contact with your Technical support!")
                    raise Exception("⚠️  Cookies expired. Contact with your Technical support!")

            else:
                self.logger.info("📝 No cookies found or cookies expired.  Contact with your Technical support!")
                raise Exception("📝 No cookies found or cookies expired.  Contact with your Technical support!")
                
            # ---------- SCRAPE EACH CITY ----------
            self.logger.info("\n🌍 SCRAPING CITIES")
            self.logger.info("-" * 80)
            
            for city_idx, city in enumerate(self.cities, 1):
                self.logger.info(f"\n📍 City {city_idx}/{len(self.cities)}: {city.title()}")
                self.logger.info("-" * 80)
                
                search_url = build_search_url(city, self.query, self.last_n_days)
                self.logger.info(f"🔗 URL: {search_url}")
                
                # Close previous page and create new one
                await page.close()
                page = await context.new_page()
                setup_response_handlers(page, self.logger)

                try:
                    self.logger.info(f"⏳ Loading marketplace page...")
                    await page.goto(search_url, wait_until="domcontentloaded", timeout=PAGE_LOAD_TIMEOUT)
                    
                    success, city_items, error = await retry_with_backoff_async(
                        lambda: scrape_city(
                            page=page,
                            city=city,
                            seen_links=self.seen_links,
                            scraper=self
                        )
                    )

                    if success and city_items:
                        self.logger.info(f"✅ Scraped {len(city_items)} items from {city.title()}")
                    else:
                        if error:
                            self.logger.info(f"❌ Failed to scrape {city.title()} after retries. Maybe, session has expired. Error: {error}")
                            raise Exception(f"❌ Failed to scrape {city.title()} after retries. Maybe, session has expired. Error: {error}")
                        self.logger.info(f"❌ Failed to scrape {city.title()} after retries. Error: {error or "Maybe, there are not listings in that city in the marketplace. Please check it!"}")
                        
                except Exception as e:
                    self.logger.info(f"❌ Error scraping {city.title()}: {e}")
                    continue

            # ---------- FINAL SUMMARY ----------
            self.logger.info("\n" + "=" * 80)
            self.logger.info("✅ SCRAPING COMPLETE!")
            self.logger.info(f"📊 Total unique listings scraped: {len(self.seen_links)}")
            self.logger.info("=" * 80)

            await browser.close()

    def start_scraping(self) -> Dict[str, Any]:
        """
        Synchronous wrapper using asyncio.run()
        Can be called from Celery, Django, or any sync code.
        """
        asyncio.run(self._async_main())
        return self.all_results
