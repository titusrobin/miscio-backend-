# app/core/config.py
import logging
from dotenv import load_dotenv # Loads environment variables from a .env file into the environment
from functools import lru_cache # Caches the result of a function so it doesn't need to be recalculated - Least Recently Used
from typing import List, Optional # type hints, which are annotations that specify what type a variable should be.
from pydantic_settings import BaseSettings #ensures your data has the correct types and formats. 
# (: std =)BaseSettings is a special class from Pydantic that's designed specifically for application settings - Reads values from environment variables

load_dotenv()
logger = logging.getLogger(__name__)


# New class Settings inherits from BaseSettings. 
# Creating special form that will automatically pull values from env variables.
# Eg. When creating Settings instance: looks for an env variable named API_V1_STR - If not found, it uses the default value "/api/v1"
class Settings(BaseSettings):
    API_V1_STR: str = "/api/v1"
    PROJECT_NAME: str = "Miscio AI"
    DESCRIPTION: str = "Experimental AI platform where you can teach AI assistants to enhance student engagement"

    SECRET_KEY: str #TODO: Set in .env 
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 3  # 3 days

    OPENAI_API_KEY: str
    OPENAI_API_VERSION: str = "2024-03-01-preview"
    OPENAI_ASSISTANT_MODEL: str = "gpt-4-turbo-preview"
    OPENAI_MAX_TOKENS: int = 4000
    OPENAI_TEMPERATURE: float = 0.7

    MONGODB_URL: str
    MONGODB_DB_NAME: str = "MiscioP1"
    MONGODB_MAX_POOL_SIZE: int = 10
    MONGODB_MIN_POOL_SIZE: int = 1

    # Redis is software you install on your own servers, not a third-party service
    REDIS_URL: str = "redis://localhost:6379/0" # Redis is a super-fast database that stores data in memory (RAM) instead of on disk. 
    REDIS_MAX_CONNECTIONS: int = 10
    REDIS_TIMEOUT: int = 30
    RATE_LIMIT_PER_MINUTE: int = 60
    #TODO Redis Password 

    TWILIO_ACCOUNT_SID: str
    TWILIO_AUTH_TOKEN: str
    TWILIO_WHATSAPP_NUMBER: str = "whatsapp:+14155238886"

    SENDGRID_API_KEY: str
    SENDGRID_FROM_EMAIL: str = "robin@miscio.io"
    SENDGRID_FROM_NAME: str = "Miscio Assistant"

    ALLOWED_ORIGINS: List[str] = ["http://localhost:3000", 
                                  "https://api.miscioapp.com", 
                                  "https://miscio-frontend.vercel.app",
                                  "https://miscio-frontend-*.vercel.app",]

    class Config:
        env_file = ".env" # Tells Pydantic to look for a file named .env in the project directory
        env_file_encoding = "utf-8"
        extra = "forbid" # Don't add extra fields that aren't in .env file

    def get_mongodb_settings(self) -> dict: # groups all MongoDB-related settings into a single dictionary
        """Returns MongoDB-specific settings."""
        logger.info("Getting MongoDB settings")
        return {
            "url": self.MONGODB_URL,
            "db_name": self.MONGODB_DB_NAME,
            "max_pool_size": self.MONGODB_MAX_POOL_SIZE,
            "min_pool_size": self.MONGODB_MIN_POOL_SIZE,
        }

    def get_redis_settings(self) -> dict: # groups all Redis-related settings into a single dictionary
        """Returns Redis-specific settings."""
        logger.info("Getting Redis settings")
        return {
            "url": self.REDIS_URL,
            "max_connections": self.REDIS_MAX_CONNECTIONS,
            "timeout": self.REDIS_TIMEOUT,
        }


@lru_cache() # decorator ensures the function only runs once
def get_settings() -> Settings:
    """Returns cached settings instance."""
    logger.info("Loading settings")
    return Settings()

settings = get_settings()
