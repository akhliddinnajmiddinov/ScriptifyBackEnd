import csv
import logging

logger = logging.getLogger()

class CSVExporter:
    """Handles CSV export functionality"""
    
    @staticmethod
    def export_results(output_csv_path, products):
        """Stage 4: Export results to CSV"""
        logger.info("=" * 60)
        logger.info("STAGE 4: EXPORTING RESULTS")
        logger.info("=" * 60)
        
        try:
            headers = [
                "Link",
                "Original Title",
                "Title Match Confidence",
                "Title Match Confidence Reason",
                "Generated Title",
                "AI Confidence",
                "AI Confidence Reason",
                "Original Price",
                "Total Amazon Price",
                "Difference",
                "Products"
            ]
            
            with open(output_csv_path, 'w', newline='', encoding='utf-8') as csvfile:
                writer = csv.DictWriter(csvfile, fieldnames=headers, quoting=csv.QUOTE_ALL)
                writer.writeheader()

                for product in products:
                    products_list = product.get("products", [])
                    if not products_list:
                        continue
                    products_str = CSVExporter._format_products_for_csv(products_list)
                    
                    orig_price = product.get("price", "N/A")
                    difference = "N/A"
                    try:
                        orig_price = float(orig_price) if orig_price else 0
                        amazon_price = product.get('total_amazon_price', 0)
                        difference = f"{orig_price - amazon_price:.2f} €"
                        orig_price = f"{orig_price:.2f} €"
                    except Exception as e:
                        orig_price = "N/A"
                        difference = "N/A"

                    row = {
                        "Link": product.get("link", ""),
                        "Original Title": product.get("title", ""),
                        "Title Match Confidence": f"{product.get('title_match_confidence', 0):.2f}",
                        "Title Match Confidence Reason": product.get("title_match_confidence_reason", ""),
                        "Generated Title": product.get("generated_title", ""),
                        "AI Confidence": f"{product.get('ai_confidence', 0):.2f}",
                        "AI Confidence Reason": product.get("ai_confidence_reason", ""),
                        "Original Price": orig_price,
                        "Total Amazon Price": f"{product.get('total_amazon_price', 0):.2f} €",
                        "Difference": difference,
                        "Products": products_str
                    }

                    writer.writerow(row)
            
            logger.info(f"✅ Successfully exported {len(products)} products to {output_csv_path}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Export error: {str(e)}", exc_info=True)
            return False

    @staticmethod
    def _format_products_for_csv(products_list):
        """Format products list for CSV with proper delimiters"""
        if not products_list:
            return ""

        formatted_products = []
        for product in products_list:
            product_str = "; ".join([
                f"title={product.get('title', '')}",
                f"brand={product.get('brand', '')}",
                f"model={product.get('model', '')}",
                f"quantity={product.get('quantity', 1)}",
                f"confidence={product.get('confidence', '')}",
                f"amazon_title={product.get('amazon_title', '')}",
                f"amazon_price={round(product.get('amazon_price', 0), 2)}",
                f"amazon_url={product.get('amazon_url', '')}",
            ])
            formatted_products.append(product_str)

        return " | ".join(formatted_products)
