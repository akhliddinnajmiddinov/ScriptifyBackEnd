import os
import logging
from typing import List, Dict, Any
from .ai_base import AIModelBase
from .openai_model import OpenAIModel
from .claude_model import ClaudeModel
from .config import get_ai_model_config

class AIModelRouter:
    """
    Factory class to route AI requests to the appropriate model based on environment configuration.
    Supports OpenAI GPT-4o and Claude Sonnet 4.5.
    """
    
    _instance = None
    _model = None
    
    def __new__(cls, *args, **kwargs):
        """Singleton pattern to ensure only one router instance"""
        if cls._instance is None:
            cls._instance = super(AIModelRouter, cls).__new__(cls)
        return cls._instance
    
    def __init__(self, logger, ai_model="claude"):
        """Initialize the router and load the configured model"""
        self.logger = logger
        self.ai_model = ai_model
        if self._model is None:
            self._load_model(self.ai_model)
    
    def _load_model(self, ai_model="claude") -> None:
        """Load the AI model based on AI_MODEL environment variable"""
        
        self.logger.info(f"Loading AI model: {ai_model}")
        
        if ai_model == 'claude':
            self._model = ClaudeModel()
            self.logger.info("Using Claude Sonnet 4.5 model")
        elif ai_model == 'openai':
            self._model = OpenAIModel()
            self.logger.info("Using OpenAI GPT-4o model")
        else:
            self.logger.warning(f"Unknown AI_MODEL value: {ai_model}. Defaulting to Claude")
            self._model = ClaudeModel()
        
        # Validate API key
        if not self._model.validate_api_key():
            raise ValueError(f"API key not configured for {self._model.model_name}")
    
    def get_model(self) -> AIModelBase:
        """Get the currently loaded AI model"""
        if self._model is None:
            self._load_model(self.ai_model)
        return self._model
    
    def generate_title(self, prompt: str, image_urls: List[str], schema: Dict[str, Any]) -> Dict[str, Any]:
        """
        Generate title using the configured AI model.
        
        Args:
            prompt: The analysis prompt
            image_urls: List of image URLs to analyze
            schema: JSON schema for structured output
            
        Returns:
            Dictionary with response content and metadata
        """
        model = self.get_model()
        ai_config = get_ai_model_config()
        
        if ai_config.use_file_based_images:
            self.logger.info("Using file-based image upload method")
            return model.generate_title_from_urls_as_files(prompt, image_urls, schema)
        else:
            self.logger.info("Using direct URL image method")
            return model.generate_title(prompt, image_urls, schema)
    
    def get_model_name(self) -> str:
        """Get the name of the currently loaded model"""
        model = self.get_model()
        return model.model_name
    
    @staticmethod
    def reset():
        """Reset the singleton instance (useful for testing)"""
        AIModelRouter._instance = None
        AIModelRouter._model = None
