import csv
import logging

logger = logging.getLogger()

class CSVImporter:
    """Handles CSV import functionality"""
    
    @staticmethod
    def import_csv(input_csv_path):
        """Stage 1: Import CSV data"""
        logger.info("=" * 60)
        logger.info("STAGE 1: IMPORTING CSV DATA")
        logger.info("=" * 60)
        
        products = []
        
        try:
            with open(input_csv_path, 'r', encoding='utf-8') as csvfile:
                reader = csv.DictReader(csvfile)
                required_headers = ['Link', 'Description', 'Title', 'Price', 'Image_URLs']
                
                if not all(h in reader.fieldnames for h in required_headers):
                    missing = [h for h in required_headers if h not in reader.fieldnames]
                    raise ValueError(f"Missing columns: {', '.join(missing)}")
                
                for i, row in enumerate(reader):
                    product = {
                        'id': i,
                        'link': row.get('Link', ''),
                        'description': row.get('Description', ''),
                        'title': row.get('Title', ''),
                        'price': row.get('Price', ''),
                        'image_urls': [
                            u.strip() for u in (row.get('Image_URLs', '') or "").split(';') if u.strip()
                        ]
                    }
                    products.append(product)
                    logger.info(f"[{i+1}] Imported: {product['title']}")
            
            logger.info(f"✅ Successfully imported {len(products)} products")
            return True, products
            
        except Exception as e:
            logger.error(f"❌ Import error: {str(e)}", exc_info=True)
            return False, []
