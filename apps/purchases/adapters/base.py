from abc import ABC, abstractmethod
from typing import Dict, Optional, Any, Tuple
from decimal import Decimal
from datetime import datetime
from django.utils import timezone


class BasePurchasesAdapter(ABC):
    """
    Abstract base class for platform-specific purchase order adapters.
    Each platform (Vinted, Amazon, Kleinanzeigen, etc.) should implement this.
    """
    
    # Platform identifier - must be set by subclasses
    platform: str = None
    
    def __init__(self):
        if not self.platform:
            raise ValueError(f"{self.__class__.__name__} must define a 'platform' attribute")
    
    @abstractmethod
    def normalize(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normalize platform-specific data to Purchases model format.
        
        Args:
            raw_data: Platform-specific raw data (from scraper/API)
            
        Returns:
            Dictionary with normalized fields matching Purchases model
        """
        pass
    
    @abstractmethod
    def extract_external_id(self, raw_data: Dict[str, Any]) -> str:
        """
        Extract the platform-specific order/conversation ID.
        
        Args:
            raw_data: Platform-specific raw data
            
        Returns:
            String ID unique to this platform
        """
        pass
    
    def normalize_price(self, price_data: Any, currency: Optional[str] = None) -> Tuple[Optional[Decimal], Optional[str]]:
        """
        Normalize price data from various formats to (amount, currency) tuple.
        
        Handles:
        - [amount, currency] arrays
        - {"amount": ..., "currency_code": ...} objects
        - Simple numeric values with separate currency
        - None values
        """
        if price_data is None:
            return None, None
        
        # Handle [amount, currency] format
        if isinstance(price_data, list) and len(price_data) == 2:
            amount = price_data[0]
            curr = price_data[1]
            try:
                return Decimal(str(amount)), str(curr) if curr else None
            except (ValueError, TypeError):
                return None, None
        
        # Handle {"amount": ..., "currency_code": ...} format
        if isinstance(price_data, dict):
            amount = price_data.get('amount') or price_data.get('price')
            curr = price_data.get('currency_code') or price_data.get('currency') or currency
            try:
                return Decimal(str(amount)), str(curr) if curr else None
            except (ValueError, TypeError):
                return None, None
        
        # Handle simple numeric value
        if isinstance(price_data, (int, float, str)):
            try:
                return Decimal(str(price_data)), currency
            except (ValueError, TypeError):
                return None, currency
        
        return None, currency
    
    def normalize_datetime(self, dt_value: Any) -> Optional[datetime]:
        """
        Normalize datetime from various formats to timezone-aware datetime.
        
        Handles:
        - ISO format strings
        - Unix timestamps
        - datetime objects
        - None
        """
        if dt_value is None:
            return None
        
        if isinstance(dt_value, datetime):
            if timezone.is_aware(dt_value):
                return timezone.make_naive(dt_value)
            return dt_value
        
        if isinstance(dt_value, str):
            dt_value = dt_value.strip()
            if not dt_value:
                return None
                
            # Try ISO format
            try:
                # Handle with timezone
                if 'T' in dt_value or '+' in dt_value or dt_value.endswith('Z'):
                    dt = datetime.fromisoformat(dt_value.replace('Z', '+00:00'))
                    return timezone.make_naive(dt) if timezone.is_aware(dt) else dt
                
                # Handle simple date format (e.g., 2026-02-20 13:57:50)
                # Parse as naive
                return datetime.strptime(dt_value, '%Y-%m-%d %H:%M:%S')
            except (ValueError, AttributeError):
                pass
                
            # Try just date format
            try:
                return datetime.strptime(dt_value, '%Y-%m-%d')
            except (ValueError, AttributeError):
                pass
        
            # Unix timestamp - create as aware UTC then convert to naive Platform Time
            try:
                dt = datetime.fromtimestamp(dt_value, tz=timezone.utc)
                return timezone.make_naive(dt)
            except (ValueError, OSError):
                pass
        
        return None
    
    def normalize_order_status(self, status: Any) -> Optional[str]:
        """
        Normalize order status to standard choices.
        Override in subclasses for platform-specific mappings.
        """
        if not status:
            return None
        
        status_str = str(status).lower()
        
        # Standard mappings
        status_map = {
            'new': 'new',
            'pending': 'pending',
            'processing': 'processing',
            'shipped': 'shipped',
            'delivered': 'delivered',
            'completed': 'completed',
            'complete': 'completed',
            'cancelled': 'cancelled',
            'canceled': 'cancelled',
            'returned': 'returned',
            'refunded': 'refunded',
            'uncompleted': 'uncompleted',
        }
        
        return status_map.get(status_str)
    
    def extract_primary_listing_url(self, items: list) -> Optional[str]:
        """
        Extract primary listing URL from items array.
        Returns first item's URL if available.
        """
        if items and isinstance(items, list) and len(items) > 0:
            first_item = items[0]
            if isinstance(first_item, dict):
                return first_item.get('url')
        return None
    
    def validate(self, normalized_data: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        """
        Validate normalized data before saving.
        
        Returns:
            (is_valid, error_message)
        """
        if not normalized_data.get('external_id'):
            return False, "external_id is required"
        
        if not normalized_data.get('product_title'):
            return False, "product_title is required"
        
        return True, None
    
    def get_chat_link(self, external_id: str) -> Optional[str]:
        """
        Generate platform-specific chat/conversation link.
        Override in subclasses for platform-specific URLs.
        """
        return None
