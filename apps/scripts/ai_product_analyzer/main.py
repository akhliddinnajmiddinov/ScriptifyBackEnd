import os
import sys
import logging
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv
from tqdm import tqdm

from logger_setup import setup_logging
from csv_importer import CSVImporter
from title_generator import TitleGenerator
from price_fetcher import PriceFetcher
from csv_exporter import CSVExporter

load_dotenv()
logger = setup_logging()

class CLIProductAnalyzer:
    """Main orchestrator for the product processing pipeline"""
    
    def __init__(self):
        self.input_csv = os.getenv('INPUT_CSV_PATH')
        self.output_folder = os.getenv('OUTPUT_FOLDER')
        self.openai_api_key = os.getenv('OPENAI_API_KEY')
        self.keepa_api_key = os.getenv('KEEPA_API_KEY')
        self.max_images = int(os.getenv('MAX_INPUT_IMAGES_TO_OPENAI', '15'))
        
        if not self.input_csv:
            raise ValueError("INPUT_CSV_PATH environment variable not set")
        if not self.output_folder:
            raise ValueError("OUTPUT_FOLDER environment variable not set")
        if not self.openai_api_key:
            raise ValueError("OPENAI_API_KEY environment variable not set")
        
        Path(self.output_folder).mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        self.output_csv = Path(self.output_folder) / f'output_{timestamp}.csv'
        
        self.products = []
        self.title_generator = TitleGenerator(self.openai_api_key, self.max_images)
        
        logger.info("CLI Processor initialized")
        logger.info(f"Input CSV: {self.input_csv}")
        logger.info(f"Output Folder: {self.output_folder}")
        logger.info(f"Output CSV: {self.output_csv}")

    def run(self):
        """Execute the complete workflow"""
        logger.info("\n" + "=" * 60)
        logger.info("STARTING PRODUCT PROCESSING PIPELINE")
        logger.info("=" * 60 + "\n")
        
        try:
            # Stage 1: Import
            success, self.products = CSVImporter.import_csv(self.input_csv)
            if not success:
                logger.error("Import failed, aborting")
                return False
            
            # Stages 2-3: Process products (title generation + price fetching)
            self._process_products()
            
            # Stage 4: Export
            if not CSVExporter.export_results(str(self.output_csv), self.products):
                logger.error("Export failed")
                return False
            
            logger.info("\n" + "=" * 60)
            logger.info("✅ PIPELINE COMPLETED SUCCESSFULLY")
            logger.info("=" * 60 + "\n")
            return True
            
        except Exception as e:
            logger.error(f"Pipeline error: {str(e)}", exc_info=True)
            return False

    def _process_products(self):
        """Process each product through title generation and price fetching"""
        logger.info("=" * 60)
        logger.info("STAGE 2-3: PROCESSING PRODUCTS (TITLE GENERATION + PRICE FETCHING)")
        logger.info("=" * 60)
        
        with tqdm(total=len(self.products), desc="Processing Products", unit="product", leave=True) as pbar:
            for i, product in enumerate(self.products):
                logger.info(f"\n{'='*60}")
                logger.info(f"[{i+1}/{len(self.products)}] Processing: {product['title']}")
                logger.info(f"{'='*60}")
                
                # Generate title for this product
                self.title_generator.generate_title(product)
                
                # Fetch prices for this product's sub-products
                PriceFetcher.fetch_prices(product)
                
                pbar.update(1)
        
        logger.info(f"\n✅ Processing complete for all {len(self.products)} products")

def main():
    try:
        processor = CLIProductAnalyzer()
        success = processor.run()
        sys.exit(0 if success else 1)
    except Exception as e:
        logger.error(f"Fatal error: {str(e)}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    main()