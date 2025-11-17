import os
from typing import List, Dict, Any
import anthropic
from .retry_with_backoff import retry_with_backoff
from .ai_base import AIModelBase
from .config import get_ai_model_config
from .image_utils import download_and_encode_image

class ClaudeModel(AIModelBase):
    """Claude Sonnet 4.5 implementation"""
    
    def __init__(self):
        super().__init__()
        ai_config = get_ai_model_config()
        self.model_name = ai_config.claude_model
        self.api_key = os.environ.get('ANTHROPIC_API_KEY', '')
        self.client = anthropic.Anthropic(api_key=self.api_key)
        self.max_tokens = 16384
        self.temperature = 0.2
    
    def validate_api_key(self) -> bool:
        """Validate Claude API key is set"""
        if not self.api_key:
            print("ANTHROPIC_API_KEY not set in environment variables")
            return False
        return True
    
    def generate_title(self, prompt: str, image_urls: List[str], schema: Dict[str, Any]) -> Dict[str, Any]:
        """
        Generate title using Claude Sonnet 4.5 with vision capabilities.
        
        Args:
            prompt: The analysis prompt
            image_urls: List of image URLs to analyze
            schema: JSON schema for structured output (used for context, Claude uses instructions)
            
        Returns:
            Dictionary with response content and metadata
        """
        if not self.validate_api_key():
            raise ValueError("Claude API key not configured")
        
        # Build content with text and images
        content = [
            {"type": "text", "text": prompt}
        ]
        
        # Add images to content
        for url in image_urls:
            content.append({
                "type": "image",
                "source": {
                    "type": "url",
                    "url": url
                }
            })
        
        # Add JSON schema instruction
        schema_instruction = f"\n\nIMPORTANT: Return ONLY valid JSON matching this schema:\n{schema}"
        if content and content[0]["type"] == "text":
            content[0]["text"] += schema_instruction
        
        def call_claude():
            return self.client.messages.create(
                model=self.model_name,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                messages=[
                    {
                        "role": "user",
                        "content": content
                    }
                ]
            )
        
        success, response, error = retry_with_backoff(call_claude)
        
        if not success or not response:
            raise Exception(f"Claude API call failed: {error}")
        return {
            "content": response.content[0].text,
            "model": self.model_name,
            "usage": {
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
                "total_tokens": response.usage.input_tokens + response.usage.output_tokens
            }
        }


    def generate_title_from_urls_as_files(self, prompt: str, image_urls: List[str], schema: Dict[str, Any]) -> Dict[str, Any]:
        """
        Generate title by downloading images from URLs and using file-based logic.
        This method extracts mimetype from HTTP response headers for better reliability.
        
        Args:
            prompt: The analysis prompt
            image_urls: List of image URLs to download and analyze
            schema: JSON schema for structured output
            
        Returns:
            Dictionary with response content and metadata
        """
        if not self.validate_api_key():
            raise ValueError("Claude API key not configured")
        
        # Build content with text and images
        content = [
            {"type": "text", "text": prompt}
        ]
        
        for url in image_urls:
            try:
                success, result, error = retry_with_backoff(lambda: download_and_encode_image(url))
                
                if not success or not result:
                    raise Exception(str(error))
                
                base64_image, mimetype = result
                print(f"Downloaded image with mimetype: {mimetype}")

                content.append({
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": mimetype,
                        "data": base64_image
                    }
                })
            except Exception as e:
                print(f"Failed to download image from {url}: {e}")
                continue

        # Add JSON schema instruction
        schema_instruction = f"\n\nIMPORTANT: Return ONLY valid JSON matching this schema:\n{schema}"
        if content and content[0]["type"] == "text":
            content[0]["text"] += schema_instruction
        
        def call_claude():
            return self.client.messages.create(
                model=self.model_name,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                messages=[
                    {
                        "role": "user",
                        "content": content
                    }
                ]
            )
        
        response = call_claude()
        
        if not response:
            raise Exception(f"Claude API call failed")
        
        return {
            "content": response.content[0].text,
            "model": self.model_name,
            "usage": {
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
                "total_tokens": response.usage.input_tokens + response.usage.output_tokens
            }
        }
