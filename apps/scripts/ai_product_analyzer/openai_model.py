import os
import logging
from typing import List, Dict, Any
from openai import OpenAI
from retry_with_backoff import retry_with_backoff
from ai_base import AIModelBase
from config import get_ai_model_config


logger = logging.getLogger()

class OpenAIModel(AIModelBase):
    """OpenAI GPT-4o implementation"""
    
    def __init__(self):
        super().__init__()
        ai_config = get_ai_model_config()
        self.model_name = ai_config.openai_model
        self.api_key = os.environ.get('OPENAI_API_KEY', '')
        self.client = OpenAI(api_key=self.api_key)
        self.max_tokens = 16384
        self.temperature = 0.2
    
    def validate_api_key(self) -> bool:
        """Validate OpenAI API key is set"""
        if not self.api_key:
            logger.error("OPENAI_API_KEY not set in environment variables")
            return False
        return True
    
    def generate_title(self, prompt: str, image_urls: List[str], schema: Dict[str, Any]) -> Dict[str, Any]:
        """
        Generate title using OpenAI GPT-4o with vision capabilities.
        
        Args:
            prompt: The analysis prompt
            image_urls: List of image URLs to analyze
            schema: JSON schema for structured output
            
        Returns:
            Dictionary with response content and metadata
        """
        if not self.validate_api_key():
            raise ValueError("OpenAI API key not configured")
        
        # Prepare messages with text and image URLs
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    *[{"type": "image_url", "image_url": {"url": url, "detail": "low"}} for url in image_urls]
                ]
            }
        ]
        
        def call_openai():
            return self.client.chat.completions.create(
                model=self.model_name,
                messages=messages,
                response_format={
                    "type": "json_schema",
                    "json_schema": schema
                },
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                timeout=120
            )
        
        success, response, error = retry_with_backoff(call_openai)
        print(response)
        
        if not success or not response:
            raise Exception(f"OpenAI API call failed: {error}")
        
        return {
            "content": response.choices[0].message.content,
            "model": self.model_name,
            "usage": {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens
            }
        }
