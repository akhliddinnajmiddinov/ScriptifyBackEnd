from typing import Dict, Any, Optional
from .base import BasePurchasesAdapter
from decimal import Decimal


class VintedAdapter(BasePurchasesAdapter):
    """
    Adapter for Vinted platform data normalization.
    Converts Vinted scraper output to Purchases format.
    """
    
    platform = 'vinted'
    
    def extract_external_id(self, raw_data: Dict[str, Any]) -> str:
        """Extract Vinted conversation_id"""
        return str(raw_data.get('conversation_id') or raw_data.get('id', ''))
    
    def normalize(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normalize Vinted scraper data to Purchases format.
        
        Expected input format (from VintedMyOrdersScraper):
        {
            "conversation_id": ...,
            "seller_id": ...,
            "seller_name": ...,
            "order_status": ...,
            "product": ...,
            "items": [...],
            ...
        }
        """
        external_id = self.extract_external_id(raw_data)
        
        # Normalize prices
        item_price, item_currency = self.normalize_price(
            raw_data.get('item_price'),
            raw_data.get('purchase_currency')
        )
        purchase_price, purchase_currency = self.normalize_price(
            raw_data.get('purchase_price'),
            raw_data.get('purchase_currency')
        )
        service_fee, service_fee_currency = self.normalize_price(
            raw_data.get('service_fee')
        )
        shipment_price, shipment_price_currency = self.normalize_price(
            raw_data.get('shipment_price')
        )
        total_price, total_price_currency = self.normalize_price(
            raw_data.get('total_price'),
            raw_data.get('purchase_currency')
        )
        refunded_amount, refunded_currency = self.normalize_price(
            raw_data.get('refunded_amount')
        )
        
        # Normalize dates
        purchased_at = self.normalize_datetime(
            raw_data.get('purchase_at') or raw_data.get('purchase_date')
        )
        updated_at = self.normalize_datetime(raw_data.get('updated_at'))
        
        # Extract items
        items = raw_data.get('items', [])
        
        # Normalize order status
        order_status = self.normalize_order_status(
            raw_data.get('order_status')
        )
        
        # Build seller info
        seller_info = {
            'seller_id': raw_data.get('seller_id'),
            'seller_name': raw_data.get('seller_name'),
            'username': raw_data.get('username') or raw_data.get('seller_name'),
        }
        
        # Platform-specific data (store original Vinted fields)
        platform_data = {
            'transaction_id': raw_data.get('transaction_id'),
            'transaction_status': raw_data.get('transaction_status'),
            'transaction_completed': raw_data.get('transaction_completed'),
            'transaction_status_updated_at': raw_data.get('transaction_status_updated_at'),
            'chat_messages': raw_data.get('chat_messages'),
            'unread': raw_data.get('unread'),
            'tracking_status': raw_data.get('tracking_status'),
        }
        
        normalized = {
            'platform': self.platform,
            'external_id': external_id,
            'seller_info': seller_info,
            'order_status': order_status,
            'product_title': raw_data.get('product') or raw_data.get('title', ''),
            'description': raw_data.get('description'),
            'primary_listing_url': None,
            'purchased_at': purchased_at,
            'updated_at': updated_at,
            'item_price': item_price,
            'item_price_currency': item_currency,
            'purchase_price': purchase_price,
            'purchase_price_currency': purchase_currency,
            'service_fee': service_fee,
            'service_fee_currency': service_fee_currency,
            'shipment_price': shipment_price,
            'shipment_price_currency': shipment_price_currency,
            'total_price': total_price,
            'total_price_currency': total_price_currency,
            'refunded_amount': refunded_amount,
            'refunded_amount_currency': refunded_currency,
            'shipment_id': str(raw_data.get('shipment_id')) if raw_data.get('shipment_id') else None,
            'tracking_code': raw_data.get('shipment_tracking_code') or raw_data.get('tracking_code'),
            'tracking_url': raw_data.get('tracking_url'),
            'items': items,
            'platform_data': platform_data,
        }
        
        # Validate
        is_valid, error = self.validate(normalized)
        if not is_valid:
            raise ValueError(f"Invalid normalized data: {error}")
        
        return normalized
    
    def normalize_order_status(self, status: Any) -> Optional[str]:
        """
        Vinted-specific status normalization.
        Maps Vinted statuses to standard order statuses.
        """
        if not status:
            return None
        
        status_str = str(status).lower()
        
        # Vinted-specific mappings
        vinted_map = {
            'new': 'new',
            'pending': 'pending',
            'processing': 'processing',
            'shipped': 'shipped',
            'delivered': 'delivered',
            'completed': 'completed',
            'cancelled': 'cancelled',
            'canceled': 'cancelled',
            'returned': 'returned',
            'refunded': 'refunded',
            'uncompleted': 'uncompleted',
        }
        
        return vinted_map.get(status_str, status_str)
    
    def get_chat_link(self, external_id: str) -> Optional[str]:
        """Generate Vinted chat link"""
        if external_id:
            return f"https://www.vinted.de/inbox/{external_id}"
        return None
