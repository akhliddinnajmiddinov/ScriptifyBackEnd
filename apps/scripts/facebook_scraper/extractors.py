import json
import re
from typing import Dict, List, Optional
from datetime import datetime, timezone
from playwright.async_api import async_playwright, Browser, BrowserContext, Page


def extract_products_from_html(html: str) -> List[Dict]:
    """Extract initial product data embedded in the HTML page."""
    products = []
    # Find all script tags with type="application/json"
    pattern = r'<script[^>]*(?:type="application/json"[^>]*data-sjs|data-sjs[^>]*type="application/json")[^>]*>(.*?)</script>'
    matches = re.findall(pattern, html, re.DOTALL)
    for script_content in matches:
        try:
            data = json.loads(script_content)
            # Look for marketplace_search data in the nested structure
            edges = []
            
            # Navigate through the nested structure to find edges
            def find_edges(obj):
                if isinstance(obj, dict):
                    # Check if this dict has the marketplace_search structure
                    if "marketplace_search" in obj:
                        ms = obj["marketplace_search"]
                        if isinstance(ms, dict) and "feed_units" in ms:
                            fu = ms["feed_units"]
                            if isinstance(fu, dict) and "edges" in fu:
                                return fu["edges"]
                    
                    # Recursively search in all dict values
                    for value in obj.values():
                        result = find_edges(value)
                        if result:
                            return result
                elif isinstance(obj, list):
                    for item in obj:
                        result = find_edges(item)
                        if result:
                            return result
                return None
            
            edges = find_edges(data)
            
            if edges:
                for edge in edges:
                    listing = edge.get("node", {}).get("listing")
                    if not listing:
                        continue

                    # ✅ Skip listings where upsell_type is not null
                    tracking_str = edge.get("node", {}).get("tracking", "")
                    try:
                        tracking = json.loads(tracking_str)
                        rank_obj = json.loads(tracking.get("commerce_rank_obj", "{}"))
                        # print(listing.get("marketplace_listing_title"),rank_obj.get("upsell_type"))
                        if rank_obj.get("upsell_type") is not None:
                            continue  # skip upsell listings
                    except Exception:
                        pass  # if tracking parsing fails, keep the item


                    price = listing.get("listing_price", {})
                    listing_id = listing.get("id")

                    product = {
                        "id": listing_id,
                        "processed": False,
                        "title": listing.get("marketplace_listing_title"),
                        "description": "",
                        "image_urls": [],
                        "price": price.get("amount"),
                        "currency": price.get("currency", "USD"),
                        "link": f"https://www.facebook.com/marketplace/item/{listing_id}/",
                    }
                    products.append(product)
            
            if products:
                return products
        
        except Exception as e:
            continue
    

def extract_products_from_graphql(response_text: str) -> List[Dict]:
    """Extract product data from Facebook GraphQL response."""
    try:
        data = json.loads(response_text)
    except json.JSONDecodeError as e:
        return []

    products = []
    edges = (
        data.get("data", {})
        .get("marketplace_search", {})
        .get("feed_units", {})
        .get("edges", [])
    )

    for edge in edges:
        listing = edge.get("node", {}).get("listing")
        if not listing:
            continue

        # ✅ Skip listings where upsell_type is not null
        tracking_str = edge.get("node", {}).get("tracking", "")
        try:
            tracking = json.loads(tracking_str)
            rank_obj = json.loads(tracking.get("commerce_rank_obj", "{}"))
            # print(listing.get("marketplace_listing_title"),rank_obj.get("upsell_type"))
            if rank_obj.get("upsell_type") is not None:
                continue  # skip upsell listings
        except Exception:
            pass  # if tracking parsing fails, keep the item


        price = listing.get("listing_price", {})
        listing_id = listing.get("id")

        product = {
            "id": listing_id,
            "processed": False,
            "title": listing.get("marketplace_listing_title"),
            "price": price.get("amount"),
            "currency": price.get("currency", "USD"),
            "link": f"https://www.facebook.com/marketplace/item/{listing_id}/",
        }
        products.append(product)

    return products

# ----------------------------------------------------------------------
# 2. Response handlers – update global dict in-place
# ----------------------------------------------------------------------
def setup_response_handlers(page: Page):
    # ------------------------------------------------------------------
    # 1. INITIAL PAGE LOAD – HTML-embedded JSON
    # ------------------------------------------------------------------
    async def handle_initial_html(resp):
        global api_buffer
        if resp.request.method != "GET" or "search" not in resp.url:
            return
        try:
            text = await resp.text()
            new = extract_products_from_html(text)
            if new:
                print(f"HTML → {len(new)} items")
                api_buffer.extend(new)
        except Exception as e:
            print("HTML parse error:", e)

    # ------------------------------------------------------------------
    # 2. SCROLLING – GraphQL feed updates
    # ------------------------------------------------------------------
    async def handle_graphql_scroll(resp):
        global api_buffer
        if resp.request.method != "POST" or "/api/graphql/" not in resp.url:
            return
        try:
            text = await resp.text()
            new = extract_products_from_graphql(text)
            if new:
                print(f"GraphQL → {len(new)} items")
                api_buffer.extend(new)
        except Exception as e:
            pass
    
    async def handle_photos(response):
        if response.request.method != "POST" or "/api/graphql/" not in response.url:
            return
        try:
            payload = await response.json()
            print(payload)
            item_id = get_id_from_payload(payload)
            if not item_id or item_id not in items_dict:
                return

            photos = extract_photos(payload)
            if photos:
                items_dict[item_id]["image_urls"] = photos
            
        except Exception as e:
            print(e)
            pass

    async def handle_details(response):
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
        except Exception as e:
            pass

    page.on("response", handle_initial_html)
    page.on("response", handle_graphql_scroll)
    page.on("response", handle_photos)
    page.on("response", handle_details)


# ----------------------------------------------------------------------
# 3. Extractors
# ----------------------------------------------------------------------
def get_id_from_payload(payload: dict) -> Optional[str]:
    try:
        target = payload.get("data", {}) \
            .get("viewer", {}) \
            .get("marketplace_product_details_page", {}) \
            .get("target", {})
        return str(target.get("id")) if target.get("id") else None
    except:
        return None

def extract_photos(payload: dict) -> List[str]:
    photos = []
    try:
        target = payload.get("data", {}) \
            .get("viewer", {}) \
            .get("marketplace_product_details_page", {}) \
            .get("target", {})
        for p in target.get("listing_photos", []):
            uri = p.get("image", {}).get("uri")
            if uri:
                photos.append(uri)
    except:
        pass
    return photos

def extract_details(payload: dict) -> Optional[Dict]:
    try:
        product_details_type = payload.get("data", {}) \
            .get("viewer", {}) \
            .get("marketplace_product_details_page", {}) \
            .get("product_details_type", "")

        if product_details_type != "FOR_SALE_ITEM":
            return None

        target = payload.get("data", {}) \
            .get("viewer", {}) \
            .get("marketplace_product_details_page", {}) \
            .get("target", {})

        title = target.get("marketplace_listing_title", "")
        description = target.get("redacted_description", {}).get("text", "")
        price_obj = target.get("listing_price", {})
        price = price_obj.get("amount", "")
        currency = price_obj.get("currency", "UNKNOWN")

        description += "\nAttributes:\n" + "\n".join([
            f"{a.get('attribute_name','')}: {a.get('value','')}"
            for a in target.get("attribute_data", [])
        ])

        listed_date = None
        ts = target.get("creation_time")
        if ts:
            try:
                listed_date = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            except:
                listed_date = "Invalid"

        return {
            "link": "",
            "title": title,
            "description": description,
            "price": price,
            "currency": currency,
            "listed_date": listed_date,
        }
    except:
        return None
