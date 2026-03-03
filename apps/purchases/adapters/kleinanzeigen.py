from typing import Dict, Any, Optional
from .base import BasePurchasesAdapter


class KleinanzeigenAdapter(BasePurchasesAdapter):
    """
    Adapter for Kleinanzeigen (eBay Kleinanzeigen) platform data normalization.
    """
    
    platform = 'kleinanzeigen'
    
    def extract_external_id(self, raw_data: Dict[str, Any]) -> str:
        """Extract Kleinanzeigen conversation/order ID"""
        return str(raw_data.get('conversation_id') or raw_data.get('ad_id', ''))
    
    def normalize(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normalize Kleinanzeigen data to Purchases format.
        Stub implementation for future use.
        """
        external_id = self.extract_external_id(raw_data)
        
        # Basic normalization structure
        normalized = {
            'platform': self.platform,
            'external_id': external_id,
            'product_title': raw_data.get('title', 'Kleinanzeigen Order'),
            'order_status': self.normalize_order_status(raw_data.get('order_status')),
            'items': raw_data.get('items', []),
            'platform_data': raw_data,
        }
        
        is_valid, error = self.validate(normalized)
        if not is_valid:
            raise ValueError(f"Invalid normalized data: {error}")
        
        return normalized
    
    def get_chat_link(self, external_id: str) -> Optional[str]:
        """Generate Kleinanzeigen chat link"""
        if external_id:
            return f"https://www.kleinanzeigen.de/m-nachrichten/{external_id}"
        return None
