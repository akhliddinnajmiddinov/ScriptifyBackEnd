import os
import sys
import logging
from datetime import datetime
from pathlib import Path
from tqdm import tqdm

class TqdmLoggingHandler(logging.StreamHandler):
    """Custom handler that writes logs using tqdm.write() to avoid progress bar interference"""
    def emit(self, record):
        try:
            msg = self.format(record)
            tqdm.write(msg, file=sys.stdout)
            self.flush()
        except Exception:
            self.handleError(record)

def setup_logging():
    """Configure logging for CLI application with tqdm compatibility"""
    log_formatter = logging.Formatter(
        '%(asctime)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    log_dir = Path(os.getcwd()) / 'logs'
    log_dir.mkdir(exist_ok=True)
    
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    log_filename = log_dir / f'cli_importer_{timestamp}.log'
    
    file_handler = logging.FileHandler(log_filename)
    file_handler.setFormatter(log_formatter)
    file_handler.setLevel(logging.DEBUG)

    console_handler = TqdmLoggingHandler(sys.stdout)
    console_handler.setFormatter(log_formatter)
    console_handler.setLevel(logging.INFO)

    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    return logger
