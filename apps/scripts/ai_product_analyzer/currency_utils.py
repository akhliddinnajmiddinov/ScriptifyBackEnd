import requests
import os
from dotenv import load_dotenv
from .retry_with_backoff import retry_with_backoff

load_dotenv()

class CurrencyConverter:
    def __init__(self, api_key: str = None, default_to: str = 'EUR'):
        self.api_key = api_key or os.getenv('EXCHANGE_RATE_API_KEY')
        if not self.api_key:
            raise ValueError("EXCHANGE_RATE_API_KEY not found")
        
        self.default_to = default_to
        self._rates = None
        self._base = None
        self._fetch_rates(default_to)


    def _fetch_rates(self, to_currency: str):
        url = f"https://v6.exchangerate-api.com/v6/{self.api_key}/latest/{to_currency}"
        
        def api_call():
            return requests.get(url)
        
        success, response, error = retry_with_backoff(api_call)
        
        if not success:
            raise ConnectionError(f"API failed after retries: {error}")
        
        if response.status_code != 200:
            raise ConnectionError(f"HTTP {response.status_code}")
        
        data = response.json()
        if data.get('result') != 'success':
            raise ValueError(f"API error: {data.get('error-type', 'Unknown')}")
        
        self._rates = data['conversion_rates']
        self._base = to_currency

    def convert(self, price, from_currency: str, to_currency: str = None) -> float:
        to_currency = to_currency or self.default_to
        
        try:
            price = float(price)
        except (TypeError, ValueError):
            return price

        if from_currency == to_currency:
            return price

        # Fetch only if base changed or not loaded
        if self._base != to_currency or self._rates is None:
            self._fetch_rates(to_currency)

        if from_currency not in self._rates:
            raise ValueError(f"Unsupported currency: {from_currency}")

        # price in from_currency to to_currency
        converted = price / self._rates[from_currency]
        return round(converted, 2)