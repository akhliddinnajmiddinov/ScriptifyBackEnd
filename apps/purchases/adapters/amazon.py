from typing import Dict, Any, Optional
from .base import BasePurchasesAdapter


class AmazonAdapter(BasePurchasesAdapter):
    """
    Adapter for Amazon platform data normalization.
    Converts Amazon order data to Purchases format.
    """
    
    platform = 'amazon'
    
    def extract_external_id(self, raw_data: Dict[str, Any]) -> str:
        """Extract Amazon order ID"""
        return str(raw_data.get('order_id') or raw_data.get('amazon_order_id', ''))
    
    def normalize(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normalize Amazon order data to Purchases format.
        
        Expected input format:
        {
            "order_id": ...,
            "seller": ...,
            "items": [...],
            ...
        }
        """
        external_id = self.extract_external_id(raw_data)
        
        # Normalize prices (Amazon format may differ)
        total_price, total_currency = self.normalize_price(
            raw_data.get('order_total'),
            raw_data.get('currency')
        )
        
        # Normalize dates
        purchased_at = self.normalize_datetime(
            raw_data.get('purchase_date') or raw_data.get('order_date')
        )
        
        # Extract items
        items = raw_data.get('items', [])
        primary_listing_url = self.extract_primary_listing_url(items)
        
        normalized = {
            'platform': self.platform,
            'external_id': external_id,
            'seller_info': {
                'seller_name': raw_data.get('seller'),
                'marketplace': raw_data.get('marketplace'),
            },
            'order_status': self.normalize_order_status(raw_data.get('order_status')),
            'product_title': raw_data.get('title') or self._extract_title_from_items(items),
            'primary_listing_url': primary_listing_url,
            'purchased_at': purchased_at,
            'total_price': total_price,
            'total_price_currency': total_currency,
            'tracking_code': raw_data.get('tracking_number'),
            'items': items,
            'platform_data': {
                'marketplace_id': raw_data.get('marketplace_id'),
                'fulfillment_channel': raw_data.get('fulfillment_channel'),
            },
        }
        
        is_valid, error = self.validate(normalized)
        if not is_valid:
            raise ValueError(f"Invalid normalized data: {error}")
        
        return normalized
    
    def _extract_title_from_items(self, items: list) -> str:
        """Extract title from first item if available"""
        if items and isinstance(items, list) and len(items) > 0:
            first_item = items[0]
            if isinstance(first_item, dict):
                return first_item.get('title', 'Amazon Order')
        return 'Amazon Order'
    
    def get_chat_link(self, external_id: str) -> Optional[str]:
        """Generate Amazon chat link (if applicable)"""
        return None
