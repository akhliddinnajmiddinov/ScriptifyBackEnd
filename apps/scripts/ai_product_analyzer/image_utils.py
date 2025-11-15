import os
import logging
import base64
import requests
from typing import Tuple
from .retry_with_backoff import retry_with_backoff

logger = logging.getLogger()

def get_mimetype_from_url(url: str) -> str:
    """
    Extract mimetype from HTTP response headers.
    Falls back to extension-based detection if headers don't provide it.
    
    Args:
        url: The image URL to fetch
        
    Returns:
        The mimetype string (e.g., 'image/jpeg')
    """
    try:
        # Make a HEAD request to get headers without downloading full image
        response = requests.head(url, timeout=10, allow_redirects=True)
        
        # Try to get mimetype from Content-Type header
        # print("response.headers", response.headers)
        content_type = response.headers.get('content-type', '').lower()
        if content_type:
            # Extract just the mimetype part (before any semicolon)
            mimetype = content_type.split(';')[0].strip()
            if mimetype.startswith('image/'):
                logger.info(f"Detected mimetype from headers: {mimetype}")
                return mimetype
    except Exception as e:
        logger.warning(f"Failed to fetch headers from {url}: {e}")
    
    # Fallback: detect from URL extension
    return get_mimetype_from_extension(url)


def get_mimetype_from_extension(url_or_path: str) -> str:
    """
    Determine mimetype from file extension.
    
    Args:
        url_or_path: URL or file path to extract extension from
        
    Returns:
        The mimetype string (e.g., 'image/jpeg')
    """
    ext = os.path.splitext(url_or_path)[1].lower()
    # print("EXT", ext)
    media_type_map = {
        '.jpg': 'image/jpeg',
        '.jpeg': 'image/jpeg',
        '.png': 'image/png',
        '.gif': 'image/gif',
        '.webp': 'image/webp',
        '.bmp': 'image/bmp',
        '.tiff': 'image/tiff',
        '.svg': 'image/svg+xml'
    }
    
    mimetype = media_type_map.get(ext, 'image/jpeg')
    logger.info(f"Detected mimetype from extension: {mimetype}")
    return mimetype


def download_and_encode_image(url: str) -> Tuple[str, str]:
    """
    Download image from URL and encode as base64.
    
    Args:
        url: The image URL to download
        
    Returns:
        Tuple of (base64_string, mimetype)
    """
    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        
        # Get mimetype from response headers
        content_type = response.headers.get('Content-Type', '').lower()
        # print(response.headers, content_type)
        if content_type:
            mimetype = content_type.split(';')[0].strip()
            if mimetype.startswith('image/'):
                logger.info(f"Downloaded image with mimetype: {mimetype}")
                base64_image = base64.standard_b64encode(response.content).decode('utf-8')
                return base64_image, mimetype
        
        # Fallback to extension-based detection
        mimetype = get_mimetype_from_extension(url)
        base64_image = base64.standard_b64encode(response.content).decode('utf-8')
        return base64_image, mimetype
        
    except Exception as e:
        logger.error(f"Failed to download image from {url}: {e}")
        raise
