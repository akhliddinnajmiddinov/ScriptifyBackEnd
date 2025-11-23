import os
from typing import List
from dotenv import load_dotenv

load_dotenv()

class RetryConfig:
    """Configuration for retry logic with exponential backoff"""
    def __init__(self):
        self.attempts = int(os.getenv('RETRY_MAX_ATTEMPTS', '3'))
        self.backoff_base_sec = float(os.getenv('RETRY_BACKOFF_BASE_SEC', '2.0'))
        self.backoff_max_sec = float(os.getenv('RETRY_BACKOFF_MAX_SEC', '60.0'))


def get_retry_config() -> RetryConfig:
    """Get retry configuration from environment or defaults"""
    return RetryConfig()


class AIModelConfig:
    """Configuration for AI models"""
    def __init__(self):
        self.openai_model = os.getenv('OPENAI_MODEL_NAME', 'gpt-4o')
        self.claude_model = os.getenv('CLAUDE_MODEL_NAME', 'claude-sonnet-4-20250514')
        self.use_file_based_images = os.getenv('USE_FILE_BASED_IMAGES', 'false').lower() in ['true', '1', 'yes']
        self.claude_quota_limit_error_texts = [
            "Your credit balance is too low to access the Anthropic API",
            "You have reached your specified API usage limits"
        ]
        self.openai_quota_limit_error_texts = [
            "you exceeded your current quota",
            "insufficient_quota"
        ]

def get_ai_model_config() -> AIModelConfig:
    """Get AI model configuration from environment or defaults"""
    return AIModelConfig()