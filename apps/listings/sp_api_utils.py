"""
Amazon SP-API utility functions for the listings app.

Two API endpoints are used:
  1. getItemOffersBatch (Products API) — pricing data
     - Up to 20 ASINs per request
     - Rate limit: 0.1 req/s, burst 1
  2. CatalogItems.get_catalog_item — listing data (title, images)
     - Rate limit: 5 req/s, burst 5

Marketplace: DE (Germany), ItemCondition: New.
"""
import random
import time
import logging
from typing import Callable, TypeVar, Tuple, Optional, Dict, List

T = TypeVar('T')
logger = logging.getLogger(__name__)

BATCH_SIZE = 20
DE_MARKETPLACE_ID = "A1PA6795UKMFR9"


def retry_with_backoff(
    func: Callable[[], T],
    max_attempts: int = 3,
    backoff_base_sec: float = 2.0,
    backoff_max_sec: float = 60.0,
) -> Tuple[bool, Optional[T], Optional[str]]:
    """
    Retry a callable with exponential back-off + jitter.
    Returns (success, result_or_None, error_or_None).
    """
    attempt = 0
    error: Optional[str] = None
    while attempt < max_attempts:
        try:
            result = func()
            return True, result, None
        except Exception as e:
            error = str(e)
            wait = min(backoff_max_sec, backoff_base_sec * (2 ** attempt))
            wait = wait * (0.5 + random.random())  # jitter
            logger.warning(
                f"retry_with_backoff attempt {attempt + 1}/{max_attempts} failed: {error}. "
                f"Sleeping {wait:.1f}s before retry."
            )
            time.sleep(wait)
            attempt += 1
    return False, None, error


# ---------------------------------------------------------------------------
# Catalog Items API — title, images, product URL
# ---------------------------------------------------------------------------

def fetch_catalog_data(
    catalog_api, asin_values: List[str]
) -> Dict[str, Optional[dict]]:
    """
    Fetch catalog data (title, images, product URL) for a list of ASINs
    using the CatalogItems API (get_catalog_item).

    Rate: 5 req/s, burst 5 — we call one ASIN at a time with a small delay.

    Args:
        catalog_api: CatalogItems client instance (marketplace=Marketplaces.DE,
                     version=CatalogItemsVersion.LATEST)
        asin_values: List of ASIN strings

    Returns:
        Dict mapping ASIN string -> parsed catalog data (or None on failure).
    """
    results: Dict[str, Optional[dict]] = {}

    for i, asin in enumerate(asin_values):
        success, response, error = retry_with_backoff(
            lambda a=asin: catalog_api.get_catalog_item(
                asin=a,
                marketplaceIds=[DE_MARKETPLACE_ID],
                includedData=["summaries", "images"],
            ),
            max_attempts=2,
        )
        # print("catalog response", response if response else None)

        if not success or response is None:
            logger.warning(f"CatalogItems: Failed to fetch {asin}: {error}")
            results[asin] = None
        else:
            logger.debug(f"CatalogItems: Successfully fetched {asin}, payload keys: {list(response.payload.keys()) if isinstance(response.payload, dict) else 'list'}")
            results[asin] = _parse_catalog_response(asin, response.payload)

        # Rate limiting: 5 req/s → sleep 0.2s between calls
        if i < len(asin_values) - 1:
            time.sleep(0.22)

    return results


def _parse_catalog_response(asin_value: str, payload: dict) -> Optional[dict]:
    """
    Parse the CatalogItems response for a single ASIN.

    Extracts:
      - title (from summaries)
      - images (list of image URLs)
      - product_url (constructed Amazon DE URL)
    """
    try:
        # --- Title from summaries ---
        logger.debug(f"Parsing catalog response for ASIN {asin_value}, payload keys: {list(payload.keys()) if isinstance(payload, dict) else 'not a dict'}")
        title = None
        summaries = payload.get('summaries', [])
        for summary in summaries:
            if summary.get('marketplaceId') == DE_MARKETPLACE_ID:
                title = summary.get('itemName')
                break
        # Fallback: take the first summary's title
        if not title and summaries:
            title = summaries[0].get('itemName')

        # --- Images ---
        # Group images by variant and select the highest resolution image for each variant
        image_urls = []
        images_data = payload.get('images', [])
        
        # Find the correct marketplace image set
        image_set = None
        for img_set in images_data:
            if img_set.get('marketplaceId') == DE_MARKETPLACE_ID:
                image_set = img_set
                break
        # Fallback: take images from the first marketplace
        if not image_set and images_data:
            image_set = images_data[0]
        
        if image_set:
            # Group images by variant
            variant_groups = {}
            for img in image_set.get('images', []):
                variant = img.get('variant', 'MAIN')  # Default to MAIN if variant is missing
                url = img.get('link')
                width = img.get('width', 0)
                height = img.get('height', 0)
                resolution = width * height  # Calculate total pixels
                
                if url:
                    # Initialize variant group if it doesn't exist
                    if variant not in variant_groups:
                        variant_groups[variant] = {
                            'url': url,
                            'resolution': resolution,
                        }
                    # Update if this image has higher resolution
                    elif resolution > variant_groups[variant]['resolution']:
                        variant_groups[variant] = {
                            'url': url,
                            'resolution': resolution,
                        }
            
            # Extract URLs, sorted by variant name for consistency
            image_urls = [variant_groups[v]['url'] for v in sorted(variant_groups.keys())]

        return {
            'title': title,
            'images': image_urls,
            'product_url': f"https://www.amazon.de/dp/{asin_value}",
        }

    except Exception as e:
        logger.error(f"Error parsing catalog data for ASIN {asin_value}: {e}")
        return None


# ---------------------------------------------------------------------------
# Products API — pricing (getItemOffersBatch)
# ---------------------------------------------------------------------------

def fetch_min_prices_batch(
    products_api, asin_values: List[str]
) -> Dict[str, Optional[dict]]:
    """
    Fetch lowest-price offers for a list of ASINs by calling get_item_offers
    individually for each ASIN. This ensures that if one ASIN fails, others can still be processed.

    Rate limit: 0.5 req/s (2 seconds between calls)

    Returns:
        Dict mapping ASIN string -> parsed pricing data (or None on failure).
    """
    results: Dict[str, Optional[dict]] = {}
    
    logger.info(f"Fetching offers individually for {len(asin_values)} ASINs: {asin_values}")

    for i, asin in enumerate(asin_values):
        try:
            # Fetch offers for a single ASIN using get_item_offers
            success, response, error = retry_with_backoff(
                lambda a=asin: products_api.get_item_offers(
                    asin=a,
                    item_condition='New',
                    customer_type='Consumer',
                    MarketplaceId=DE_MARKETPLACE_ID,
                ),
                max_attempts=2,
            )

            if not success or response is None:
                logger.warning(f"Failed to fetch offers for ASIN {asin}: {error}")
                results[asin] = None
            else:
                # Parse the response payload
                payload = response.payload if hasattr(response, 'payload') else response
                if payload:
                    logger.debug(f"Parsing offers response for ASIN {asin}, payload keys: {list(payload.keys()) if isinstance(payload, dict) else 'not a dict'}")
                    parsed = _parse_offers_response(asin, payload)
                    if parsed:
                        logger.info(f"Successfully parsed offers for ASIN {asin}, min_price: {parsed.get('min_price')}")
                    else:
                        logger.warning(f"Failed to parse offers for ASIN {asin}")
                    results[asin] = parsed
                else:
                    logger.warning(f"Empty payload for ASIN {asin}")
                    results[asin] = None

        except Exception as e:
            logger.error(f"Error fetching offers for ASIN {asin}: {e}")
            results[asin] = None

        # Rate limiting: 0.5 req/s = 2 seconds between calls
        # Only sleep if not the last item
        if i < len(asin_values) - 1:
            time.sleep(2)

    return results


def fetch_single_asin_data(
    catalog_api, products_api, asin_value: str
) -> Tuple[Optional[dict], Optional[dict]]:
    """
    Fetch both catalog and pricing data for a single ASIN.
    This allows processing ASINs individually so one failure doesn't affect others.
    
    The two APIs have separate rate limits, so we only need to respect each API's limit.
    
    Returns:
        Tuple of (catalog_data, pricing_data) - either can be None on failure.
    """
    # Fetch catalog data
    catalog_result = None
    try:
        success, response, error = retry_with_backoff(
            lambda: catalog_api.get_catalog_item(
                asin=asin_value,
                marketplaceIds=[DE_MARKETPLACE_ID],
                includedData=["summaries", "images"],
            ),
            max_attempts=2,
        )
        # print("catalog response", response if response else None)
        if success and response:
            catalog_result = _parse_catalog_response(asin_value, response.payload)
    except Exception as e:
        logger.warning(f"Failed to fetch catalog data for ASIN {asin_value}: {e}")
    
    # Fetch pricing data
    pricing_result = None
    try:
        success, response, error = retry_with_backoff(
            lambda: products_api.get_item_offers(
                asin=asin_value,
                item_condition='New',
                # customer_type='Consumer',
                MarketplaceId=DE_MARKETPLACE_ID,
            ),
            max_attempts=2,
        )
        # print("pricing response", response if response else None)
        if success and response:
            payload = response.payload if hasattr(response, 'payload') else response
            if payload:
                pricing_result = _parse_offers_response(asin_value, payload)
    except Exception as e:
        logger.warning(f"Failed to fetch pricing data for ASIN {asin_value}: {e}")
    
    # Rate limiting: offers API is the bottleneck (0.5 req/s = 2s between calls)
    # Catalog API (2 req/s = 0.5s) is faster, so the 2s wait covers both APIs
    time.sleep(2)
    
    return catalog_result, pricing_result


def _extract_asin_from_uri(uri: str) -> Optional[str]:
    """Extract ASIN from a URI like /products/pricing/v0/items/{ASIN}/offers."""
    if '/items/' in uri:
        return uri.split('/items/')[-1].split('/offers')[0]
    return None


def _parse_money(money: dict) -> Tuple[float, str]:
    """Extract (amount, currency) from a Money object like {CurrencyCode, Amount}."""
    return float(money.get('Amount', 0)), money.get('CurrencyCode', '')


def _parse_offers_response(asin_value: str, payload: dict) -> Optional[dict]:
    """
    Parse the offers payload for a single ASIN.

    Finds the absolute lowest price from ALL sources (LowestPrices, Offers, BuyBoxPrices)
    with condition "new", then matches it to the corresponding offer from the Offers array.

    Returns:
      - min_price, currency (absolute lowest from all sources, condition "new")
      - cheapest_offer (complete offer details including seller, feedback, shipping, etc.)
      - total_offer_count
      - all_offers_url
      - lowest_prices (all LowestPrices entries for reference)
      - buy_box_prices (all BuyBoxPrices entries for reference)
    """
    try:
        summary = payload.get('Summary', {})
        offers = payload.get('Offers', [])

        # --- 1. Find absolute min_price from ALL sources (only "new" condition) ---
        # Check LowestPrices
        min_price_landed = float('inf')
        min_price_currency = 'EUR'

        for lp in summary.get('LowestPrices', []):
            condition = lp.get('condition', '').lower()
            if condition == 'new':
                landed_data = lp.get('LandedPrice', {})
                landed_amt, landed_cur = _parse_money(landed_data)
                if 0 <= landed_amt < min_price_landed:
                    min_price_landed = landed_amt
                    min_price_currency = landed_cur

        # Check BuyBoxPrices (condition "New")
        for bbp in summary.get('BuyBoxPrices', []):
            condition = bbp.get('condition', '').lower()
            if condition == 'new':
                landed_data = bbp.get('LandedPrice', {})
                landed_amt, landed_cur = _parse_money(landed_data)
                if 0 <= landed_amt < min_price_landed:
                    min_price_landed = landed_amt
                    min_price_currency = landed_cur

        # Check individual Offers (SubCondition "new")
        for offer in offers:
            if offer.get('SubCondition', '').lower() == 'new':
                listing_price, _ = _parse_money(offer.get('ListingPrice', {}))
                shipping, _ = _parse_money(offer.get('Shipping', {}))
                landed = listing_price + shipping
                if 0 <= landed < min_price_landed:
                    min_price_landed = landed
                    min_price_currency = offer.get('ListingPrice', {}).get('CurrencyCode', 'EUR')

        # If no "new" condition price found, return None
        if min_price_landed == float('inf'):
            return {
                'min_price': None,
                'currency': None,
                'cheapest_offer': None,
            }

        final_min_price = round(min_price_landed, 2)
        final_currency = min_price_currency

        # --- 2. Find the offer in Offers array that matches min_price ---
        # We look for offers with SubCondition == "new" and landed_price == min_price
        # Prefer BuyBox winner if multiple matches exist
        cheapest_offer = None
        tolerance = 0.000000001  # Small tolerance for floating point comparison

        # First pass: find exact match, prefer BuyBox winner
        for offer in offers:
            # Only consider "new" condition offers
            if offer.get('SubCondition', '').lower() != 'new':
                continue

            listing_price, _ = _parse_money(offer.get('ListingPrice', {}))
            shipping, _ = _parse_money(offer.get('Shipping', {}))
            landed = listing_price + shipping

            # Check if this offer matches the min_price (within tolerance)
            if abs(landed - min_price_landed) <= tolerance:
                seller_id = offer.get('SellerId', '')
                is_buybox_winner = offer.get('IsBuyBoxWinner', False)
                offer_data = {
                    'offer_url': f"https://www.amazon.de/dp/{asin_value}?m={seller_id}" if seller_id else None,
                }

                # Prefer BuyBox winner if we haven't found one yet, or if this is a BuyBox winner
                if cheapest_offer is None or is_buybox_winner:
                    cheapest_offer = offer_data
                    # If we found a BuyBox winner, we can stop (it's the best match)
                    if is_buybox_winner:
                        break

        # If no exact match found, find the closest "new" condition offer
        if cheapest_offer is None:
            closest_landed = float('inf')
            for offer in offers:
                if offer.get('SubCondition', '').lower() != 'new':
                    continue

                listing_price, _ = _parse_money(offer.get('ListingPrice', {}))
                shipping, _ = _parse_money(offer.get('Shipping', {}))
                landed = listing_price + shipping

                # Find the closest offer to min_price
                if landed >= min_price_landed and landed < closest_landed:
                    closest_landed = landed
                    seller_id = offer.get('SellerId', '')
                    cheapest_offer = {
                        'offer_url': f"https://www.amazon.de/dp/{asin_value}?m={seller_id}" if seller_id else None,
                    }

        # Only return what's needed for the frontend (matching Listing model fields + offer_url)
        return {
            'min_price': final_min_price,
            'currency': final_currency,
            'cheapest_offer': cheapest_offer,
        }

    except Exception as e:
        logger.error(f"Error parsing offers for ASIN {asin_value}: {e}")
        return None


# ---------------------------------------------------------------------------
# Combined: merge catalog + pricing into one dict
# ---------------------------------------------------------------------------

def merge_listing_data(
    asin_value: str,
    catalog_data: Optional[dict],
    pricing_data: Optional[dict],
) -> dict:
    """
    Merge catalog data (title, images, URL) and pricing data (min_price, etc.)
    into a single dict to be stored in Asin.min_listing_data.
    
    The cheapest_offer will include the offer_url, and we also include
    title and images from catalog_data for the listing.
    """
    result = {'asin': asin_value}

    if catalog_data:
        result['title'] = catalog_data.get('title')
        result['images'] = catalog_data.get('images', [])
        result['product_url'] = catalog_data.get('product_url')

    if pricing_data:
        result['min_price'] = pricing_data.get('min_price')
        result['currency'] = pricing_data.get('currency')
        result['cheapest_offer'] = pricing_data.get('cheapest_offer')

    return result
