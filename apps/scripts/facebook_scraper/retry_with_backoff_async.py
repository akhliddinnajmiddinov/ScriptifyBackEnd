import asyncio
import random
import time
import json
from typing import Callable, TypeVar, Tuple, Optional, Awaitable
import logging

from .config import get_retry_config

logger = logging.getLogger()

T = TypeVar('T')

async def retry_with_backoff_async(func: Callable[[], Awaitable[T]]) -> Tuple[bool, Optional[T], Optional[str]]:
    cfg = get_retry_config()
    attempt = 0
    error: Optional[str] = None
    while attempt < cfg.attempts:
        try:
            result = await func()
            return True, result, None
        except Exception as e:
            error = str(e)
            logger.info(error)

            payload = {}
            refill_ms = None
            try:
                payload = json.loads(str(e).split(":", 1)[-1].strip())
                refill_ms = payload.get("refillIn")
                refill_ms = float(refill_ms) + 5000
            except:
                pass

            if refill_ms is not None:
                logger.info(f"Refill in limit exceeded error: {refill_ms} ms")
                wait = refill_ms / 1000
            else:
                wait = min(cfg.backoff_max_sec, cfg.backoff_base_sec * (2 ** attempt))
                wait = wait * (0.5 + random.random())

            logger.info(f"⏳ Retrying in {wait:.1f} seconds (attempt {attempt + 1}/{cfg.attempts})...")
            await asyncio.sleep(wait)
            attempt += 1
    return False, None, error
