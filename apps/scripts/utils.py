import logging
import os
import json
from datetime import datetime
from threading import Lock
from typing import Any, Dict

def get_run_logger(run_id, log_path):
    name = f"scraper.run.{run_id}"
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)

    # Avoid duplicate handlers
    if not any(
        isinstance(h, logging.handlers.RotatingFileHandler) and 
        getattr(h, 'baseFilename', None) == os.path.abspath(log_path)
        for h in logger.handlers
    ):
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        handler = logging.handlers.RotatingFileHandler(
            log_path, maxBytes=10*1024*1024, backupCount=5
        )
        handler.setFormatter(logging.Formatter('[%(asctime)s] %(levelname)s: %(message)s'))
        logger.addHandler(handler)

    logger.propagate = False
    return logger


class ResultWriter:
    """
    Over-writes the result file on every call (mode='w').
    Keeps the JSON structure:
        {
            "status": "running" | "complete",
            "completed_at": "...",          # only when complete
            "data": <your full result dict>
        }
    """

    def __init__(self, result_path: str, logger: logging.Logger):
        self.result_path = result_path
        self.logger = logger
        self.lock = Lock()                     # protects file writes
        os.makedirs(os.path.dirname(result_path), exist_ok=True)

    # --------------------------------------------------------------------- #
    def write(self, payload: Dict[str, Any]):
        """Thread-safe full overwrite."""
        with self.lock:
            try:
                with open(self.result_path, "w", encoding="utf-8") as f:
                    json.dump(payload, f, indent=2, ensure_ascii=False)
            except Exception as e:
                self.logger.error(f"ResultWriter write error: {e}")