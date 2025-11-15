import os
import sys
import logging
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv
from tqdm import tqdm

from .logger_setup import setup_logging
from .importer import Importer
from .title_generator import TitleGenerator
from .price_fetcher import PriceFetcher
from .organize_result import organize_result

load_dotenv()

class AIProductAnalyzer:
    """Main orchestrator for the product processing pipeline"""
    
    def __init__(self, run, script, input_data, logger, writer):
        self.run = run
        self.logger = logger
        self.writer = writer
        self.script = script

        self.validated_group = "Validated"
        self.excluded_group = "Excluded"
        self.all_results = {self.validated_group: [], self.excluded_group: []}

        input_file_paths = self.run.input_file_paths
        self.input_path = input_file_paths.get('products')
        print("self.input_path")
        print(self.input_path)
        self.openai_api_key = os.getenv('OPENAI_API_KEY')
        self.keepa_api_key = os.getenv('KEEPA_API_KEY')
        self.max_images = int(os.getenv('MAX_INPUT_IMAGES_TO_OPENAI', '15'))
        
        if not self.input_path:
            raise ValueError("Input data is not given")
        if not self.openai_api_key:
            raise ValueError("OPENAI_API_KEY environment variable not set")
        
        self.products = []
        self.title_generator = TitleGenerator(logger, self.openai_api_key, self.max_images)
        
        logger.info("CLI Processor initialized")

    def start_processing(self):
        """Execute the complete workflow"""
        self.logger.info("STARTING PRODUCT PROCESSING PIPELINE")
        
        try:
            # Stage 1: Import
            success, self.products = Importer.import_data(self.input_path, self.logger)
            if not success:
                self.logger.error("Import failed, aborting")
                return False

            # Stages 2-3: Process products (title generation + price fetching)
            self._process_products()
            
            # Stage 4: Export
            try:
                self.writer.write(self.products)
            except Exception as e:
                self.logger.error("Export failed")
                return False
            
            self.logger.info("✅ PIPELINE COMPLETED SUCCESSFULLY")
            return True
            
        except Exception as e:
            self.logger.error(f"Pipeline error: {str(e)}", exc_info=True)
            return False

    def _process_products(self):
        """Process each product through title generation and price fetching"""
        self.logger.info("STAGE 2-3: PROCESSING PRODUCTS (TITLE GENERATION + PRICE FETCHING)")
        
        for i, product in enumerate(self.products):
            self.logger.info(f"[{i+1}/{len(self.products)}] Processing: {product['title']}")
            
            
            # Generate title for this product
            excluded_product = self.title_generator.generate_title(product)
            
            if excluded_product:
                self.all_results[self.excluded_group].append(excluded_product)
            print("product")
            print(product)
            print("excluded_product")
            print(excluded_product)
            if len(product.get('products', []) or []):
                self.all_results[self.validated_group].append(product)
            
            self.writer.write(self.all_results)
            # Fetch prices for this product's sub-products
            PriceFetcher.fetch_prices(self.logger, product)
            organize_result(product)

            self.writer.write(self.all_results)
        
        self.logger.info(f"\n✅ Processing complete for all {len(self.products)} products")
    

    def get_all_results(self):
        return self.all_results