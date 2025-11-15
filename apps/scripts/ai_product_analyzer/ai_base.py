from abc import ABC, abstractmethod
from typing import List, Dict, Any

class AIModelBase(ABC):
    """Abstract base class for AI model implementations"""
    
    def __init__(self):
        self.model_name = None
        self.api_key = None
    
    @abstractmethod
    def generate_title(self, prompt: str, image_urls: List[str], schema: Dict[str, Any]) -> Dict[str, Any]:
        """
        Generate title and product analysis from prompt and images.
        
        Args:
            prompt: The analysis prompt
            image_urls: List of image URLs to analyze
            schema: JSON schema for structured output
            
        Returns:
            Dictionary with response content and metadata
        """
        pass

    @abstractmethod
    def generate_title_from_urls_as_files(self, prompt: str, image_paths: List[str], schema: Dict[str, Any]) -> Dict[str, Any]:
        """
        Generate title and product analysis from prompt and image files.
        
        Args:
            prompt: The analysis prompt
            image_paths: List of local image file paths to analyze
            schema: JSON schema for structured output
            
        Returns:
            Dictionary with response content and metadata
        """
        pass
    
    @abstractmethod
    def validate_api_key(self) -> bool:
        """Validate that API key is properly configured"""
        pass
