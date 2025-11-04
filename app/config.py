"""
Application configuration module.

This module defines a `Settings` class that holds configuration values for
the application.  The preferred implementation uses `pydantic-settings`
to load values from environment variables or `.env` files; however,
`pydantic-settings` is an optional dependency.  If it is not available
in the runtime environment, a simple fallback implementation based on
Python's built‑in `os` module is used instead.  This ensures that the
application can start even when optional packages are missing.

Usage::

    from .config import settings
    # access settings.JWT_SECRET, settings.HEADLESS, etc.

The `SECRET` property returns either `AUTH_SECRET` (if defined) or
`JWT_SECRET` and should be used wherever an application secret key is
required.
"""

from __future__ import annotations

import os
from typing import Optional

try:
    # Attempt to import BaseSettings from pydantic-settings.  This
    # dependency is optional and may not be installed in all
    # environments.  When available, it provides powerful features
    # for loading configuration from environment variables and `.env`
    # files.
    from pydantic_settings import BaseSettings  # type: ignore

    class Settings(BaseSettings):
        """Configuration using pydantic-settings.

        Environment variables (or entries in a `.env` file) will be
        automatically loaded and cast to the appropriate types.  Default
        values are provided for all fields so that the application can
        operate without explicit configuration.
        """

        # Auth/crypto
        JWT_SECRET: str = "helsenia_jwt_secret"
        AUTH_SECRET: Optional[str] = None

        @property
        def SECRET(self) -> str:
            """Return the preferred secret for authentication purposes."""
            return self.AUTH_SECRET or self.JWT_SECRET

        # UAZAPI
        UAZAPI_CHECK_URL: str = "https://hia-clientes.uazapi.com/chat/check"
        UAZAPI_INSTANCE_TOKEN: str = ""

        # Scraper
        HEADLESS: bool = True
        BROWSER: str = "chromium"
        USER_AGENT: str = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
        )
        MAX_RESULTS: int = 500
        PAGE_SIZE: int = 20
        MAX_PAGES_PER_QUERY: int = 1000
        LISTING_CONCURRENCY: int = 3
        PROXY_SERVER: Optional[str] = None
        
        # Retry & Resilience
        MAX_RETRIES: int = 3
        RETRY_DELAY_MS: int = 2000
        NAVIGATION_TIMEOUT: int = 45000
        SELECTOR_WAIT_TIMEOUT: int = 12000
        MAX_EMPTY_PAGES: int = 20
        CAPTCHA_COOLDOWN_BASE: int = 25
        CAPTCHA_MAX_COOLDOWN: int = 180

        # Verifier
        UAZAPI_BATCH_SIZE: int = 50
        UAZAPI_MAX_CONCURRENCY: int = 2
        UAZAPI_RETRIES: int = 3
        UAZAPI_THROTTLE_MS: int = 250
        UAZAPI_TIMEOUT: float = 15.0

        class Config:
            env_file = ".env"
            extra = "ignore"

    # Instantiate settings using pydantic-settings.
    settings: Settings = Settings()  # type: ignore[var-annotated]

except ImportError:
    # Fallback implementation when pydantic-settings is unavailable.
    # We manually read environment variables and provide defaults for
    # missing values.  Types are not automatically cast beyond what
    # `os.getenv` returns, so booleans and numbers must be parsed
    # explicitly.
    class Settings:
        """Simple fallback configuration loaded from environment variables."""

        def __init__(self) -> None:
            # Auth/crypto
            self.JWT_SECRET: str = os.getenv("JWT_SECRET", "helsenia_jwt_secret")
            auth_secret = os.getenv("AUTH_SECRET")
            self.AUTH_SECRET: Optional[str] = auth_secret if auth_secret else None

            # UAZAPI
            self.UAZAPI_CHECK_URL: str = os.getenv(
                "UAZAPI_CHECK_URL", "https://hia-clientes.uazapi.com/chat/check"
            )
            self.UAZAPI_INSTANCE_TOKEN: str = os.getenv("UAZAPI_INSTANCE_TOKEN", "")

            # Scraper
            self.HEADLESS: bool = os.getenv("HEADLESS", "True").lower() in (
                "1",
                "true",
                "yes",
            )
            self.BROWSER: str = os.getenv("BROWSER", "chromium")
            self.USER_AGENT: str = os.getenv(
                "USER_AGENT",
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36",
            )
            self.MAX_RESULTS: int = int(os.getenv("MAX_RESULTS", "500"))
            self.PAGE_SIZE: int = int(os.getenv("PAGE_SIZE", "20"))
            self.MAX_PAGES_PER_QUERY: int = int(
                os.getenv("MAX_PAGES_PER_QUERY", "1000")
            )
            self.LISTING_CONCURRENCY: int = int(
                os.getenv("LISTING_CONCURRENCY", "3")
            )
            proxy = os.getenv("PROXY_SERVER")
            self.PROXY_SERVER: Optional[str] = proxy if proxy else None
            
            # Retry & Resilience
            self.MAX_RETRIES: int = int(os.getenv("MAX_RETRIES", "3"))
            self.RETRY_DELAY_MS: int = int(os.getenv("RETRY_DELAY_MS", "2000"))
            self.NAVIGATION_TIMEOUT: int = int(os.getenv("NAVIGATION_TIMEOUT", "45000"))
            self.SELECTOR_WAIT_TIMEOUT: int = int(os.getenv("SELECTOR_WAIT_TIMEOUT", "12000"))
            self.MAX_EMPTY_PAGES: int = int(os.getenv("MAX_EMPTY_PAGES", "20"))
            self.CAPTCHA_COOLDOWN_BASE: int = int(os.getenv("CAPTCHA_COOLDOWN_BASE", "25"))
            self.CAPTCHA_MAX_COOLDOWN: int = int(os.getenv("CAPTCHA_MAX_COOLDOWN", "180"))

            # Verifier
            self.UAZAPI_BATCH_SIZE: int = int(
                os.getenv("UAZAPI_BATCH_SIZE", "50")
            )
            self.UAZAPI_MAX_CONCURRENCY: int = int(
                os.getenv("UAZAPI_MAX_CONCURRENCY", "2")
            )
            self.UAZAPI_RETRIES: int = int(os.getenv("UAZAPI_RETRIES", "3"))
            self.UAZAPI_THROTTLE_MS: int = int(
                os.getenv("UAZAPI_THROTTLE_MS", "250")
            )
            self.UAZAPI_TIMEOUT: float = float(
                os.getenv("UAZAPI_TIMEOUT", "15.0")
            )

        @property
        def SECRET(self) -> str:
            """Return the preferred secret for authentication purposes."""
            return self.AUTH_SECRET or self.JWT_SECRET

    # Instantiate settings using the fallback class.
    settings: Settings = Settings()

__all__ = ["settings", "Settings"]
