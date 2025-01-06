# app/core/config.py
from pydantic_settings import BaseSettings
from typing import List, Optional
from functools import lru_cache
import logging
from dotenv import load_dotenv

logger = logging.getLogger(__name__)
load_dotenv()


class Settings(BaseSettings):
    # API configuration
    API_V1_STR: str = "/api/v1"
    PROJECT_NAME: str = "Miscio Assistant"
    VERSION: str = "1.0.0"
    DESCRIPTION: str = "AI Assistant for School Administrators"

    # Security
    SECRET_KEY: str
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 8  # 8 days

    # OpenAI Configuration
    OPENAI_API_KEY: str
    OPENAI_API_VERSION: str = "2024-03-01-preview"
    OPENAI_ASSISTANT_MODEL: str = "gpt-4-turbo-preview"
    OPENAI_MAX_TOKENS: int = 4000
    OPENAI_TEMPERATURE: float = 0.7

    # MongoDB
    MONGODB_URL: str
    MONGODB_DB_NAME: str = "MiscioP1"
    MONGODB_MAX_POOL_SIZE: int = 10
    MONGODB_MIN_POOL_SIZE: int = 1

    # Redis Cache Configuration
    REDIS_URL: str = "redis://localhost:6379/0"
    REDIS_MAX_CONNECTIONS: int = 10
    REDIS_TIMEOUT: int = 30

    # Twilio
    TWILIO_ACCOUNT_SID: str
    TWILIO_AUTH_TOKEN: str
    TWILIO_WHATSAPP_NUMBER: str = "whatsapp:+14155238886"

    # CORS
    ALLOWED_ORIGINS: List[str] = ["http://localhost:3000"]

    # Rate Limiting
    RATE_LIMIT_PER_MINUTE: int = 60

    # Logging
    LOG_LEVEL: str = "INFO"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "forbid"

    def get_mongodb_settings(self) -> dict:
        """Returns MongoDB-specific settings."""
        logger.info("Getting MongoDB settings")
        return {
            "url": self.MONGODB_URL,
            "db_name": self.MONGODB_DB_NAME,
            "max_pool_size": self.MONGODB_MAX_POOL_SIZE,
            "min_pool_size": self.MONGODB_MIN_POOL_SIZE,
        }

    def get_redis_settings(self) -> dict:
        """Returns Redis-specific settings."""
        logger.info("Getting Redis settings")
        return {
            "url": self.REDIS_URL,
            "max_connections": self.REDIS_MAX_CONNECTIONS,
            "timeout": self.REDIS_TIMEOUT,
        }


@lru_cache()
def get_settings() -> Settings:
    """Returns cached settings instance."""
    logger.info("Loading settings")
    return Settings()


settings = get_settings()

# Remove sensitive print statements, use logging instead
import logging

logging.basicConfig(level=settings.LOG_LEVEL)
logger = logging.getLogger(__name__)
logger.info(f"Configuration loaded for {settings.PROJECT_NAME} v{settings.VERSION}")
# Access the settings

# # Print the settings
# print(f"API_V1_STR: {settings.API_V1_STR}")
# print(f"PROJECT_NAME: {settings.PROJECT_NAME}")
# print(f"VERSION: {settings.VERSION}")
# print(f"DESCRIPTION: {settings.DESCRIPTION}")
# #print(f"SECRET_KEY: {settings.SECRET_KEY}")
# #print(f"ACCESS_TOKEN_EXPIRE_MINUTES: {settings.ACCESS_TOKEN_EXPIRE_MINUTES}")
# print(f"MONGODB_URL: {settings.MONGODB_URL}")
# print(f"MONGODB_DB_NAME: {settings.MONGODB_DB_NAME}")
# print(f"REDIS_URL: {settings.REDIS_URL}")
# print(f"OPENAI_API_KEY: {settings.OPENAI_API_KEY}")
# print(f"TWILIO_ACCOUNT_SID: {settings.TWILIO_ACCOUNT_SID}")
# print(f"TWILIO_AUTH_TOKEN: {settings.TWILIO_AUTH_TOKEN}")
# print(f"TWILIO_WHATSAPP_NUMBER: {settings.TWILIO_WHATSAPP_NUMBER}")
# print(f"ALLOWED_ORIGINS: {settings.ALLOWED_ORIGINS}")
