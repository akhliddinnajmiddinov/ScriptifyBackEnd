import os
import time
import json
import requests
import logging
from datetime import datetime, timezone
from dotenv import load_dotenv
from .retry_with_backoff import retry_with_backoff


load_dotenv()

API_KEY = os.getenv("KEEPA_API_KEY")
DOMAIN = 3  # DE = 3, US = 1
BASE_URL = "https://api.keepa.com"

CSV_FIELD_MAP = {
    0: "AMAZON",
    1: "NEW",
    2: "USED"
}


def keepa_time_to_utc(minutes_since_2011):
    """Convert Keepa's minute-based timestamp to UTC datetime."""
    base_timestamp = 1293840000  # 2011-01-01 00:00:00 UTC
    return datetime.fromtimestamp(base_timestamp + minutes_since_2011 * 60, tz=timezone.utc)

def get_logger_or_null(logger):
    if logger is None:
        null_logger = logging.getLogger("null_logger")
        null_logger.addHandler(logging.NullHandler())  # swallow all logs
        return null_logger
    return logger

def extract_latest_price(csv_data, field_name):
    """
    Extract the latest valid (non -1) price and timestamp from Keepa CSV array.
    Returns (price, datetime)
    """
    index = next((i for i, name in CSV_FIELD_MAP.items() if name == field_name), None)
    if index is None or index >= len(csv_data):
        return None, None

    arr = csv_data[index]
    if not arr or len(arr) < 2:
        return None, None

    # Iterate backwards through (timestamp, price)
    for i in range(len(arr) - 1, 0, -2):
        price = arr[i]
        time_index = arr[i - 1]
        if price and price > 0:
            price_eur = round(price / 100, 2)
            price_time = keepa_time_to_utc(time_index)
            return price_eur, price_time
    return None, None

def print_token_data(data, logger):
    # 'refillIn': 54592, 'refillRate': 21, 'timestamp': 1761054169548, 'tokenFlowReduction': 0.0, 'tokensConsumed': 1, 'tokensLeft': 0
    logger.info(f"Refill: {data.get('refillIn')}")
    logger.info(f"Refill rate: {data.get('refillRate')}")
    logger.info(f"Tokens consumed: {data.get('tokensConsumed')}")
    logger.info(f"Tokens left: {data.get('tokensLeft')}")


def get_first_priced_product(search_term: str, limit: int = int(os.getenv("TOP_N_KEEPA_PRODUCTS", 5)), logger = None):
    """Search for a product on Amazon via Keepa HTTP API, return first valid price or fallback first product."""
    logger = get_logger_or_null(logger)

    if not search_term or not search_term.strip():
        logger.info("Empty search term, skipping")
        return None
    try:
        def search_asins():
            url = (
                f"{BASE_URL}/search?"
                f"key={API_KEY}&domain={DOMAIN}&type=product&term={search_term}&asins-only=1&page=0&update=0"
            )
            r = requests.get(url)
            if r.status_code != 200:
                raise Exception(f"HTTP {r.status_code}: {r.text}")
            data = r.json()
            print_token_data(data, logger)
            return data.get("asinList", [])

        success, asins, error = retry_with_backoff(search_asins)
        if not success or not asins:
            logger.info(f"No products found for '{search_term}'" + (f" - Error: {error}" if error else ""))
            return None

        first_fallback = None

        # Step 2️⃣: Loop through ASINs and check prices
        for asin in asins[:limit]:
            try:
                def query_product():
                    url = f"{BASE_URL}/product?key={API_KEY}&domain={DOMAIN}&asin={asin}&update=0"
                    r = requests.get(url)
                    if r.status_code != 200:
                        raise Exception(f"HTTP {r.status_code}: {r.text}")
                    
                    # 'refillIn': 54592, 'refillRate': 21, 'timestamp': 1761054169548, 'tokenFlowReduction': 0.0, 'tokensConsumed': 1, 'tokensLeft': 0
                    data = r.json()
                    print_token_data(data, logger)
                    return data

                success, response, error = retry_with_backoff(query_product)
                if not success or not response:
                    logger.info(f"Failed to query ASIN {asin}: {error}")
                    continue

                products = response.get("products", [])
                if not products:
                    continue

                product = products[0]
                title = product.get("title", "")
                csv_data = product.get("csv", [])
                product_url = f"https://www.amazon.de/dp/{asin}"

                if not title:
                    continue

                # Store first product (for fallback)
                if first_fallback is None:
                    first_fallback = {
                        "asin": asin,
                        "title": title,
                        "price": 0,
                        "currency": "EUR",
                        "price_time": None,
                        "url": product_url,
                    }

                # Step 3️⃣: Extract latest price + time from CSV arrays
                for price_type in ["AMAZON", "NEW", "USED"]:
                    price_value, price_time = extract_latest_price(csv_data, price_type)
                    if price_value:
                        product_info = {
                            "asin": asin,
                            "title": title,
                            "price": price_value,
                            "currency": "EUR",
                            "price_time": price_time.strftime("%Y-%m-%d %H:%M:%S UTC"),
                            "url": product_url,
                        }
                        logger.info("✅ Found:", product_info)
                        return product_info

            except Exception as e:
                logger.info(f"Error querying ASIN {asin}: {e}")
                continue

        if first_fallback:
            logger.info(f"No valid prices found for '{search_term}', returning first product fallback.")
            logger.info(f"⬅️ Fallback: {first_fallback}")
            return first_fallback
        else:
            logger.info(f"No products found at all for '{search_term}'.")
            return None

    except Exception as e:
        logger.info(f"Error in get_first_priced_product: {e}")
        return None