import time
from .keepa_http import get_first_priced_product

class PriceFetcher:
    """Handles Amazon price fetching"""
    
    @staticmethod
    def fetch_prices(logger, product):
        """Fetch Amazon prices for sub-products"""
        logger.info("→ Fetching Amazon prices for sub-products...")
        
        try:
            products_list = product.get("products", [])
            if not products_list:
                logger.warning("No sub-products identified, skipping price fetch")
                product["total_amazon_price"] = 0
                return
            
            total_price = 0

            for sub_product in products_list:
                search_term = sub_product.get("title", "")
                if not search_term:
                    search_term = f"{sub_product.get('brand', '')} {sub_product.get('model', '')}".strip()

                logger.info(f"  Searching for: {search_term}")
                
                amazon_match = get_first_priced_product(search_term, logger=logger)

                if amazon_match:
                    sub_product["amazon_title"] = amazon_match.get("title", "")
                    sub_product["amazon_price"] = amazon_match.get("price", 0)
                    sub_product["amazon_url"] = amazon_match.get("url", "")
                    sub_product["asin"] = amazon_match.get("asin", "")
                    sub_product["price_time"] = amazon_match.get("price_time", "")
                    
                    quantity = sub_product.get("quantity", 1)
                    total_price += amazon_match.get("price", 0) * quantity
                    
                    logger.info(
                        f"  ✅ Found: {amazon_match.get('title')[:50]}... "
                        f"- {amazon_match.get('price')} EUR x {quantity}"
                    )
                else:
                    logger.warning(f"  ❌ No Amazon match found")
                    sub_product["amazon_title"] = "Not found"
                    sub_product["amazon_price"] = 0
                    sub_product["amazon_url"] = ""
                    sub_product["asin"] = ""
                    sub_product["price_time"] = ""

            product["total_amazon_price"] = round(total_price, 2)
            logger.info(f"  ✅ Total Amazon Price: {total_price:.2f} EUR")
                
        except Exception as e:
            logger.error(f"Error fetching prices: {str(e)}", exc_info=True)
            product["total_amazon_price"] = 0