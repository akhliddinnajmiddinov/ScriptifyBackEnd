from .base import BasePurchasesAdapter
from .vinted import VintedAdapter
from .amazon import AmazonAdapter
from .kleinanzeigen import KleinanzeigenAdapter
from typing import Dict, Any, Optional


# Registry of available adapters
ADAPTER_REGISTRY = {
    'vinted': VintedAdapter,
    'amazon': AmazonAdapter,
    'kleinanzeigen': KleinanzeigenAdapter,
}


def get_adapter(platform: str) -> BasePurchasesAdapter:
    """
    Factory function to get the appropriate adapter for a platform.
    
    Args:
        platform: Platform identifier (e.g., 'vinted', 'amazon')
        
    Returns:
        Instance of the appropriate adapter class
        
    Raises:
        ValueError: If platform is not supported
    """
    adapter_class = ADAPTER_REGISTRY.get(platform.lower())
    if not adapter_class:
        raise ValueError(
            f"Unsupported platform: {platform}. "
            f"Available platforms: {', '.join(ADAPTER_REGISTRY.keys())}"
        )
    return adapter_class()


def normalize_purchase_data(platform: str, raw_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convenience function to normalize purchase data for any platform.
    
    Args:
        platform: Platform identifier
        raw_data: Platform-specific raw data
        
    Returns:
        Normalized data dictionary ready for Purchases model
    """
    adapter = get_adapter(platform)
    return adapter.normalize(raw_data)
