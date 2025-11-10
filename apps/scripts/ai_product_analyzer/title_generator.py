import json
import time
import logging
import re
from openai import OpenAI
from retry_with_backoff import retry_with_backoff
from ai_model_router import AIModelRouter
from response_schema import schema

logger = logging.getLogger()

class TitleGenerator:
    """Handles AI title generation using OpenAI"""
    
    def __init__(self, openai_api_key, max_images=15):
        self.client = OpenAI(api_key=openai_api_key)
        self.max_images = max_images
        self.ai_router = AIModelRouter()

    
    def generate_title(self, product):
        """Generate AI title for a product"""
        logger.info("→ Generating AI title...")
        
        try:
            description = product.get('description', '')
            original_title = product.get('title', '')
            image_urls = product.get('image_urls', [])[:self.max_images]
            
            if not description and not image_urls:
                logger.warning("No description or images, skipping title generation")
                self._set_default_title(product, original_title, "No description or images, skipping title generation")
                return
            
            prompt = self._build_prompt(description, original_title)
            
            def ai_call():
                return self.ai_router.generate_title(prompt, image_urls, schema)

            success, response, error = retry_with_backoff(ai_call)

            if not success or not response:
                logger.error(f"OpenAI API call failed: {error}")
                self._set_default_title(product, original_title, f"OpenAI API call failed: {error}")
            else:
                self._parse_response(product, response, original_title)
        
        except Exception as e:
            logger.error(f"Error generating title: {str(e)}", exc_info=True)
            self._set_default_title(product, product.get('title', ''), f"Error generating title: {str(e)}")
    
    def _build_prompt(self, description, original_title):
        """Build the OpenAI prompt for title generation"""
        return (
            f"Analyze this product listing for ink cartridges sold on a German site. "
            f"Description: {description}\n"
            f"Seller's title: \"{original_title}\"\n\n"


            f"TASKS:\n"
            f"1. IDENTIFY ALL INDIVIDUAL/MULTIPACK PRODUCTS IN THIS LISTING\n"
            f"- For EACH product, extract: exact model number, brand, the specific title(included the brand and model), quantity, confidence, and is_original, original_verification_reason.\n"
            f"- Avoid generic titles - use EXACT model numbers visible in images/description.\n"
            f"- Quantity: How many units of this product/multipack are in the listing (e.g., 1, 2, 5, etc.)\n\n"
            f"- Confidence: How confident are you in identifying this product\n\n"
            
            f"Example:\n"
            f'  "products": [\n'
            f'    {{"title": "Specific product title", "brand": "Brand name", "model": "Exact model number", "quantity": 2, "confidence": 0.85, "is_original": true, "original_verification_reason": "Official packaging with brand logo and security hologram visible"}},\n'
            f'    {{"title": "Another product title", "brand": "Brand name", "model": "Model number", "quantity": 1, "confidence": 0.7, "is_original": false, "original_verification_reason": "Labeled as compatible, no official brand packaging"}}\n'
            f'  ]\n'


            f"2. GENERATE AN OVERALL TITLE FOR THE LISTING WITH THE EXACT MODEL NUMBERS OF EACH PRODUCT IN THIS LISTING.\n\n"
            
            f"Example:\n"
            f'"ai_title": "Ankauf Ihrer leeren Canon und HP 305, HP 305XL, HP 307XL, HP 304, HP 304XL, HP 303, HP 303XL, HP 302, HP 302XL, HP 301, 301XL, 62, 62XL, 300, 300XL, 901 leere Patronen, volle überlagerte Druckerpatronen Toner",\n'


            f"3. CALCULATE CONFIDENCE SCORES AND REASONING:\n"
            f"- 1. ai_confidence (0-1): How confident are you in identifying the products?\n"
            f"   - 0.9-1.0: Clear images, visible model numbers, high certainty\n"
            f"   - 0.7-0.8: Good images, most details visible\n"
            f"   - 0.5-0.6: Moderate image quality, some uncertainty\n"
            f"   - 0.3-0.4: Poor image quality, unclear model numbers\n"
            f"   - 0.0-0.2: Very unclear, mostly guessing\n\n"
            f"   PROVIDE ai_confidence_reason: Brief explanation (1-2 sentences) why this confidence level\n\n"
            f"- 2. title_match_confidence (0-1): How well does the seller's title match the actual products?\n"
            f"   - 0.9-1.0: Seller's title perfectly matches identified products\n"
            f"   - 0.7-0.8: Seller's title mostly correct, minor differences\n"
            f"   - 0.5-0.6: Seller's title partially correct\n"
            f"   - 0.3-0.4: Seller's title has significant errors or missing info\n"
            f"   - 0.0-0.2: Seller's title is wrong or very generic\n\n"
            f"   PROVIDE title_match_confidence_reason: Brief explanation (1-2 sentences) why this confidence level\n\n"

            f"CRITICAL RULES:\n"
            f"1. MULTIPACK HANDLING:\n"
            f"   - If cartridges are bundled together in ONE package/set (multipack), treat as ONE product entry\n"
            f"   - Only create separate product entries if items are sold individually/separately\n\n"
            
            f"2. ORIGINALITY CHECK:\n"
            f"is_original = true ONLY if:\n"
            f"  - Official brand packaging visible with brand logos (Canon/HP/Epson/...)\n"
            f"  - NOTE: Cartridges themselves often DON'T show brand names - focus on PACKAGING and other specifications\n"
            f"  - Product matches official brand specifications exactly\n"
            f"  - No words like: 'kompatibel', 'compatible', 'rebuilt', 'refilled', 'nachgefüllt', 'Drittanbieter', 'generic', 'alternative'\n"
            f"  - No signs of counterfeiting (spelling errors, poor quality, mismatched logos)\n\n"
            f"is_original = false if:\n"
            f"  - Labeled as 'kompatibel', 'compatible', 'rebuilt', 'refilled', 'nachgefüllt', 'Drittanbieter', 'generic', 'alternative'\n"
            f"  - Suspicious or unclear branding\n"
            f"  - Any indication of counterfeiting or non-authenticity\n"
            f"  - When in doubt, mark as false (be conservative)\n\n"
            
            f"3. RESPONSE FORMAT EXAMPLE (JSON only, no markdown):\n"
            f"{{\n"
            f'  "ai_title": "Ankauf Ihrer leeren Canon und HP 305, HP 305XL, HP 307XL, HP 304, HP 304XL, HP 303, HP 303XL, HP 302, HP 302XL, HP 301, 301XL, 62, 62XL, 300, 300XL, 901 leere Patronen, volle überlagerte Druckerpatronen Toner",\n'
            f'  "ai_confidence": 0.85,\n'
            f'  "ai_confidence_reason": "Clear images showing exact model numbers",\n'
            f'  "title_match_confidence": 0.60,\n'
            f'  "title_match_confidence_reason": "Seller title is generic, missing specific model info",\n'
            f'  "products": [\n'
            f'    {{"title": "Specific product title", "brand": "Brand name", "model": "Exact model number", "quantity": 2, "confidence": 0.85, "is_original": true, "original_verification_reason": "Official packaging with brand logo and security hologram visible"}},\n'
            f'    {{"title": "Another product title", "brand": "Brand name", "model": "Model number", "quantity": 1, "confidence": 0.7, "is_original": false, "original_verification_reason": "Labeled as compatible, no official brand packaging"}}\n'
            f'  ]\n'
            f"}}\n\n"
            f"IMPORTANT: Return ONLY valid JSON. No explanations, no markdown code blocks."
        )
    
    def _parse_response(self, product, response, original_title):
        """Parse OpenAI response and update product"""
        try:
            cleaned_response = self._clean_response(response.get("content", ""))
            response_json = json.loads(cleaned_response)
            
            product["generated_title"] = response_json.get("ai_title", original_title)
            product["ai_confidence"] = max(0.0, min(1.0, float(response_json.get("ai_confidence", 0))))
            product["ai_confidence_reason"] = response_json.get("ai_confidence_reason", "")
            product["title_match_confidence"] = max(0.0, min(1.0, float(response_json.get("title_match_confidence", 0))))
            product["title_match_confidence_reason"] = response_json.get("title_match_confidence_reason", "")
            
            products_list = response_json.get("products", [])
            validated_products = []
            for p in products_list:
                if isinstance(p, dict) and "title" in p:
                    try:
                        quantity = int(p.get("quantity", 1))
                        if quantity < 1:
                            quantity = 1
                    except (ValueError, TypeError):
                        quantity = 1
                    
                    is_original = p.get("is_original", True)
                    if not isinstance(is_original, bool):
                        is_original = str(is_original).lower() in ['true', '1', 'yes']

                    if not is_original:
                        logger.warning(f"Filtered out due to it is not ORIGINAL: {p.get('title')}\nREASON: {p.get("original_verification_reason", "N/A")}")
                        continue
                        
                    validated_products.append({
                        "title": p.get("title", ""),
                        "brand": p.get("brand", ""),
                        "model": p.get("model", ""),
                        "quantity": quantity,
                        "confidence": max(0.0, min(1.0, float(p.get("confidence", 0))))
                    })
            
            product["products"] = validated_products
            
            logger.info(
                f"✅ Title generated: {product['generated_title'][:60]}... "
                f"(AI Conf: {product['ai_confidence']:.2f}, Match Conf: {product['title_match_confidence']:.2f}, "
                f"Products: {len(validated_products)})"
            )
            
        except json.JSONDecodeError as e:
            logger.warning(f"JSON parsing failed: {e}")
            self._set_default_title(product, original_title, f"JSON parsing failed: {e}")
    
    @staticmethod
    def _clean_response(response_text):
        """Remove Markdown code block delimiters from response"""
        if not response_text:
            return "{}"
        cleaned = re.sub(r'^\`\`\`json\s*|\s*\`\`\`$', '', response_text, flags=re.MULTILINE)
        return cleaned.strip()
    
    @staticmethod
    def _set_default_title(product, original_title, error_message):
        """Set default values when title generation fails"""
        product["generated_title"] = original_title
        product["ai_confidence"] = 0.0
        product["ai_confidence_reason"] = error_message
        product["title_match_confidence"] = 0.0
        product["title_match_confidence_reason"] = error_message
        product["products"] = []
