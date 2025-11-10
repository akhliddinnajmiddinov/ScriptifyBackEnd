import random
import time
import json
from typing import Callable, TypeVar, Tuple, Optional

from config import get_retry_config

T = TypeVar('T')


def retry_with_backoff(func: Callable[[], T]) -> Tuple[bool, Optional[T], Optional[str]]:
    cfg = get_retry_config()
    attempt = 0
    error: Optional[str] = None
    while attempt < cfg.attempts:
        try:
            result = func()
            return True, result, None
        except Exception as e:
            error = str(e)
            logger.info(error)

            payload = json.loads(str(e).split(":", 1)[-1].strip())
            refill_ms = payload.get("refillIn")
            
            try:
                refill_ms = float(refill_ms) + 5000
            except:
                refill_ms = None

            if refill_ms is not None:
                logger.info(f"Refill in limit exceeded error: {refill_ms} ms")
                wait = refill_ms / 1000  # convert milliseconds to seconds
            else:
                wait = min(cfg.backoff_max_sec, cfg.backoff_base_sec * (2 ** attempt))
                # Add jitter to avoid thundering herd
                wait = wait * (0.5 + random.random())
            time.sleep(wait)
            attempt += 1
    return False, None, error