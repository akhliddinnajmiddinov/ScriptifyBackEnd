import asyncio
import random
import json
import csv
import pandas as pd
from copy import deepcopy
from typing import Dict, List, Set, Optional
from .config import LISTINGS_PER_CITY, MAX_NO_NEW_ITEMS_ATTEMPTS
from .extractors import (
    extract_products_from_html,
    extract_products_from_graphql,
    get_id_from_payload,
    extract_photos,
    extract_details,
)

# Global state for scraping
items_dict: Dict[str, dict] = {}
api_buffer: List[dict] = []

def setup_response_handlers(page, logger):
    """Setup response handlers for HTML and GraphQL data extraction."""
    
    async def handle_initial_html(resp):
        global api_buffer
        if resp.request.method != "GET" or "search" not in resp.url:
            return
        try:
            text = await resp.text()
            new = extract_products_from_html(text)
            if new:
                api_buffer.extend(new)
                logger.info(f"  📄 HTML → {len(new)} items")
        except Exception as e:
            logger.info(f"  ⚠️  HTML parse error: {e}")

    async def handle_graphql_scroll(resp):
        global api_buffer
        if resp.request.method != "POST" or "/api/graphql/" not in resp.url:
            return
        try:
            text = await resp.text()
            new = extract_products_from_graphql(text)
            if new:
                api_buffer.extend(new)
                logger.info(f"  📊 GraphQL → {len(new)} items")
        except Exception:
            pass
    
    async def handle_photos(response):
        global items_dict
        if response.request.method != "POST" or "/api/graphql/" not in response.url:
            return
        try:
            payload = await response.json()
            item_id = get_id_from_payload(payload)
            if not item_id or item_id not in items_dict:
                return
            photos = extract_photos(payload)
            if photos:
                items_dict[item_id]["image_urls"] = photos
        except:
            pass

    async def handle_details(response):
        global items_dict
        if response.request.method != "POST" or "/api/graphql/" not in response.url:
            return
        try:
            payload = await response.json()
            item_id = get_id_from_payload(payload)
            if not item_id or item_id not in items_dict:
                return
            details = extract_details(payload)
            if details:
                items_dict[item_id].update(details)
                items_dict[item_id]['link'] = f"https://www.facebook.com/marketplace/item/{item_id}/"
        except:
            pass

    page.on("response", handle_initial_html)
    page.on("response", handle_graphql_scroll)
    page.on("response", handle_photos)
    page.on("response", handle_details)

async def drag_element(page, element, drag_distance: int = 250, steps: int = 30):
    """Perform a realistic swipe/drag on a Marketplace listing."""
    box = await element.bounding_box()
    if not box:
        return

    start_x = box["x"] + box["width"] / 2
    start_y = box["y"] + box["height"] / 2
    end_x = start_x + drag_distance * 0.7
    end_y = start_y + drag_distance * 0.8

    await page.mouse.move(start_x, start_y, steps=random.randint(8, 14))
    await page.mouse.down()
    await page.mouse.move(end_x, end_y, steps=steps)
    await asyncio.sleep(random.uniform(0.1, 0.25))
    await page.mouse.up()
    await page.mouse.move(end_x + 20, end_y + 30, steps=5)

async def scroll_to_bottom(page):
    """Scroll page to bottom."""
    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    await asyncio.sleep(1.5)

def clear_items(items: List[Dict], seen_links) -> None:
    """
    Append items to CSV file after each city to prevent data loss
    """
    if not items:
        return []
    complete_items = [
        item for item in items 
        if item.get('link')
        and item.get('title')
        and item.get('description')
        and item.get('price') is not None
        and item.get('image_urls')
    ]
    if not complete_items:
        return []
    
    new_items = []
    for idx, item in enumerate(complete_items, start=1):
        link = item.get('link')
        if link not in seen_links:
            seen_links.add(link)
            # Deepcopy and update the id
        
        new_item = deepcopy(item)
        new_item['id'] = idx
        new_items.append(new_item)

    return new_items

async def scrape_city(
    page,
    city,
    seen_links: Set[str],
    scraper = None
) -> List[Dict]:
    """
    Scrape marketplace listings for a single city.
    
    Global seen_links prevents duplicate scraping across cities
    Append data after each city to prevent data loss
    Retry logic: if no new items, scroll and wait before stopping
    """
    if not scraper:
        return
    logger = scraper.logger
    
    global items_dict, api_buffer

    listings_per_city = scraper.listings_per_city
    logger.info(f"  ⏳ Scraping up to {listings_per_city} listings...")
    
    iteration = 0
    no_new_items_count = 0
    city_scraped_count = 0
    await asyncio.sleep(15)  # Give page time to load
    
    scraper.all_results[city.title()] = []
    scraper.writer.write(scraper.all_results)

    while city_scraped_count < listings_per_city:
        iteration += 1
        logger.info(f"    🔄 Iteration {iteration}")
        new_links = [link for link in api_buffer if not link.get('processed')]
        if not new_links:
            logger.info(f"    ⚠️  No new items found. Attempt {no_new_items_count + 1}/{MAX_NO_NEW_ITEMS_ATTEMPTS}")
            no_new_items_count += 1
            
            if no_new_items_count >= MAX_NO_NEW_ITEMS_ATTEMPTS:
                logger.info(f"    ❌ No new items after {MAX_NO_NEW_ITEMS_ATTEMPTS} attempts. Stopping.")
                break
            
            logger.info("    📜 Scrolling to bottom and waiting...")
            await scroll_to_bottom(page)
            await asyncio.sleep(10)
            continue
        
        no_new_items_count = 0
        logger.info(f"    ✅ Found {len(new_links)} new items. Total: {city_scraped_count}/{listings_per_city} | Total unique: {len(seen_links)}")

        for idx, link in enumerate(new_links, 1):
            link_id = link.get('id')
            link['processed'] = True
            if city_scraped_count >= listings_per_city:
                logger.info(f"    ✅ Reached target of {listings_per_city} listings.")
                break
                
            try:
                element = await page.wait_for_selector(
                    f'a[href*="/marketplace/item/{link_id}"]', timeout=10000
                )
            except Exception as e:
                logger.info(f"      ⏭️  Skipped {link_id}: selector timeout, error: {str(e)[:50]}")
                continue

            try:
                await element.wait_for_element_state("stable", timeout=10000)
                await element.scroll_into_view_if_needed()
            except:
                logger.info(f"      ⏭️  Skipped {link_id}: not stable")
                continue

            if link_id in seen_links:
                logger.info(f"      ⏭️  Skipped {link_id}: Duplicate")
                continue

            items_to_add = clear_items(list(items_dict.values()), seen_links)
            city_scraped_count = len(items_to_add)
            if items_to_add:
                scraper.all_results[city.title()] = items_to_add
                scraper.writer.write(scraper.all_results)

            items_dict[link_id] = {
                "id": link_id,
                "link": "",
                "title": "",
                "description": "",
                "price": "",
                "currency": "",
                "image_urls": [],
                "listed_date": None
            }

            try:
                await drag_element(page, element)
                await asyncio.sleep(random.randint(3, 5))
                logger.info(f"      [{idx}/{len(new_links)}] Processed {link_id}... ({city_scraped_count}/{listings_per_city})")
                logger.info(f"      Title: {link.get('title')} | Price: {link.get('price')}")
            except Exception as e:
                logger.info(f"      ❌ Drag failed {link_id}: {e}")

        api_buffer = [link for link in api_buffer if not link.get('processed')]
    
    logger.info("  ⏳ Final wait for responses...")
    await asyncio.sleep(15)
    items_to_add = clear_items(list(items_dict.values()), seen_links)
    if items_to_add:
        scraper.all_results[city.title()] = items_to_add
        scraper.writer.write(scraper.all_results)

    items_dict.clear()
    api_buffer.clear()

    return items_to_add