"""Configuration management for the FastAPI application."""

import os
from enum import Enum
from typing import Optional

from pydantic_settings import BaseSettings
from starlette.config import Config

current_file_dir = os.path.dirname(os.path.realpath(__file__))

# Check the environment and choose the appropriate .env file
env_mode = os.getenv("ENVIRONMENT", "default")
if env_mode == "test":
    env_path = os.path.join(current_file_dir, "../../.env.test")
    try:
        config = Config(env_path)
    except Exception:
        config = Config()
elif env_mode == "production":
    config = Config()  # Do not specify env_path in production
else:
    env_path = os.path.join(current_file_dir, "../.env")
    config = Config(env_path)


class EnvironmentOption(Enum):
    LOCAL = "local"
    STAGING = "staging"
    PRODUCTION = "production"
    TEST = "test"


class AppSettings(BaseSettings):
    """Application-specific settings."""
    APP_NAME: str = config("APP_NAME", default="FastAPI Render Boilerplate")
    APP_DESCRIPTION: str = config("APP_DESCRIPTION", default="Production-ready FastAPI app with Firecrawl and Gemini")
    APP_VERSION: str = config("APP_VERSION", default="1.0.0")
    APP_LOGFILE: str = config("APP_LOGFILE", default="app.log")
    
    # API Configuration
    API_PATH: str = "/api/v1"
    
    # External API Keys
    FIRECRAWL_API_KEY: Optional[str] = config("FIRECRAWL_API_KEY", default=None)
    GEMINI_API_KEY: Optional[str] = config("GEMINI_API_KEY", default=None)
    
    # Server Configuration
    HOST: str = config("HOST", default="0.0.0.0")
    PORT: int = config("PORT", default=8000)
    DEBUG: bool = config("DEBUG", default=False)
    LOG_LEVEL: str = config("LOG_LEVEL", default="INFO")
    
    # CORS Configuration
    FRONTEND_URL: Optional[str] = config("FRONTEND_URL", default=None)
    
    # Timeouts and Limits
    SCREENSHOT_TIMEOUT_SEC: int = config("SCREENSHOT_TIMEOUT_SEC", default=120)
    SCRAPE_TIMEOUT_SEC: int = config("SCRAPE_TIMEOUT_SEC", default=60)
    
    # Worker Configuration
    WORKER_DEFAULT_MAX_RETRIES: int = config("WORKER_DEFAULT_MAX_RETRIES", default=3)




class RedisSettings(BaseSettings):
    """Redis configuration settings."""
    REDIS_HOST: str = config("REDIS_HOST", default="redis")
    REDIS_PORT: int = config("REDIS_PORT", default=6379)
    REDIS_DB: int = config("REDIS_DB", default=0)
    REDIS_URL: str = f"redis://{config('REDIS_HOST', default='redis')}:{config('REDIS_PORT', default=6379)}/{config('REDIS_DB', default=0)}"


class SecuritySettings(BaseSettings):
    """Security and authentication settings."""
    SECRET_KEY: str = config("SECRET_KEY", default="your-secret-key-change-in-production")
    ALGORITHM: str = config("ALGORITHM", default="HS256")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = config("ACCESS_TOKEN_EXPIRE_MINUTES", default=30)
    REFRESH_TOKEN_EXPIRE_DAYS: int = config("REFRESH_TOKEN_EXPIRE_DAYS", default=7)


class EnvironmentSettings(BaseSettings):
    """Environment-specific settings."""
    ENVIRONMENT: str = config("ENVIRONMENT", default="local")


class Settings(
    AppSettings,
    # DatabaseSettings,
    RedisSettings,
    SecuritySettings,
    EnvironmentSettings,
):
    """Combined application settings."""
    pass


# Global settings instance
settings = Settings()

