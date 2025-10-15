from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # Auth/crypto
    JWT_SECRET: str = "helsenia_jwt_secret"   # usa sua env
    AUTH_SECRET: str | None = None            # compat, se existir
    @property
    def SECRET(self) -> str:
        return self.AUTH_SECRET or self.JWT_SECRET

    # UAZAPI
    UAZAPI_CHECK_URL: str = "https://hia-clientes.uazapi.com/chat/check"
    UAZAPI_INSTANCE_TOKEN: str = ""

    # Scraper
    HEADLESS: bool = True
    BROWSER: str = "chromium"
    USER_AGENT: str = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36")
    MAX_RESULTS: int = 500
    PAGE_SIZE: int = 20
    MAX_PAGES_PER_QUERY: int = 1000  # da sua env

    # How many listing pages to open concurrently when extracting phone numbers.
    # Opening listing pages in parallel speeds up scraping but may increase the
    # likelihood of being blocked. Tune this value to balance speed and
    # reliability. A value of 3 means at most 3 listing pages will be opened
    # concurrently per search result page.
    LISTING_CONCURRENCY: int = 3

    # Optional proxy server for outgoing requests performed by Playwright. If
    # provided, it should be a full URL such as "http://user:pass@host:port".
    # Leave as `None` to disable proxies. Using a proxy can help avoid
    # CAPTCHAs and rate‑limiting from Google by rotating IP addresses.
    PROXY_SERVER: str | None = None

    # Verifier
    UAZAPI_BATCH_SIZE: int = 50
    UAZAPI_MAX_CONCURRENCY: int = 2
    UAZAPI_RETRIES: int = 3
    UAZAPI_THROTTLE_MS: int = 250
    UAZAPI_TIMEOUT: float = 15.0

    class Config:
        env_file = ".env"
        extra = "ignore"

settings = Settings()
