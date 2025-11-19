import csv
import json
import os
import io
from django.conf import settings

class Importer:
    """Handles CSV and JSON import functionality"""
    logger = None

    @staticmethod
    def import_data(input_path, logger):
        """Routes to appropriate importer based on file extension"""
        Importer.logger = logger
        logger.info("STAGE 1: IMPORTING DATA")
        
        extension = os.path.splitext(input_path)[1].lower()
        
        if extension == '.csv':
            return Importer._import_csv(input_path)
        elif extension == '.json':
            return Importer._import_json(input_path)
        else:
            logger.error(f"❌ Unsupported file format: {extension}")
            return False, []
    
    @staticmethod
    def _parse_cell_value(value):
        """Parse cell value - detect arrays and nested CSV"""
        if not value or not isinstance(value, str):
            return value
        
        value = value.strip()
        
        # Detect nested CSV (contains newlines)
        if '\n' in value:
            try:
                nested_reader = csv.DictReader(io.StringIO(value))
                return list(nested_reader)
            except:
                pass
        
        # Detect semicolon-separated array
        if ';' in value:
            return [v.strip() for v in value.split(';')]
        
        return [value]
    
    @staticmethod
    def _import_csv(input_csv_path):
        """Import CSV data"""
        logger = Importer.logger
        products = []
        try:
            file_path = os.path.join(settings.MEDIA_ROOT, input_csv_path)
            with open(file_path, 'r', encoding='utf-8-sig') as csvfile:
                reader = csv.DictReader(csvfile)

                headers_map = {header.lower(): header for header in reader.fieldnames}
                required_headers = ['link', 'description', 'title', 'price', 'image_urls']
                
                # Check required headers (case-insensitive)
                missing = [h for h in required_headers if h not in headers_map]
                print(headers_map)
                print(required_headers)
                if missing:
                    raise ValueError(f"Missing columns: {', '.join(missing)}")
            
                def get_item(row, key):
                    return row.get(headers_map.get(key, key), "")

                for i, row in enumerate(reader):
                    product = {
                        'id': i + 1,
                        'link': get_item(row, 'link'),
                        'description': get_item(row, 'description'),
                        'title': get_item(row, 'title'),
                        'price': get_item(row, 'price'),
                        'image_urls': Importer._parse_cell_value(get_item(row, 'image_urls'))
                    }
                    
                    # Parse any additional columns not in required_headers
                    for header in reader.fieldnames:
                        if header.lower() not in required_headers:
                            product[header] = Importer._parse_cell_value(row.get(header, ''))
                    
                    products.append(product)
            logger.info(f"✅ Successfully imported {len(products)} products from CSV")
            return True, products
        except Exception as e:
            logger.error(f"❌ CSV import error: {str(e)}", exc_info=True)
            raise Exception(f"❌ CSV import error: {str(e)}")

    @staticmethod
    def _import_json(input_json_path):
        """Import JSON data"""
        logger = Importer.logger
        products = []
        try:
            file_path = os.path.join(settings.MEDIA_ROOT, input_json_path)
            with open(file_path, 'r', encoding='utf-8') as jsonfile:
                data = json.load(jsonfile)
                
                if isinstance(data, list):
                    raw_products = data
                elif isinstance(data, dict):
                    raw_products = [data]
                else:
                    raise ValueError("JSON must be an object or array of objects")
                
                required_fields = ['link', 'description', 'title', 'price', 'image_urls']
                
                for i, item in enumerate(raw_products):
                    # Create case-insensitive key mapping
                    keys_map = {k.lower(): k for k in item.keys()}
                    
                    missing = [f for f in required_fields if f not in keys_map]
                    if missing:
                        logger.warning(f"[{i+1}] Missing fields: {', '.join(missing)}")
                        raise Exception(f"[{i+1}] Missing fields: {', '.join(missing)}")
                    
                    product = {
                        'id': i + 1,
                        'link': item.get(keys_map.get('link', 'link'), ''),
                        'description': item.get(keys_map.get('description', 'description'), ''),
                        'title': item.get(keys_map.get('title', 'title'), ''),
                        'price': item.get(keys_map.get('price', 'price'), ''),
                        'image_urls': item.get(keys_map.get('image_urls', 'image_urls'), [])
                    }
                    products.append(product)
                
            logger.info(f"✅ Successfully imported {len(products)} products from JSON")
            return True, products
        except Exception as e:
            logger.error(f"❌ JSON import error: {str(e)}", exc_info=True)
            raise Exception(f"❌ JSON import error: {str(e)}")
            