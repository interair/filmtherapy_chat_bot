from __future__ import annotations

from typing import List

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Telegram Bot
    telegram_token: str = Field(..., env="TELEGRAM_TOKEN")
    admins: str = Field(default="", env="ADMINS")  # Keep as string to avoid JSON parsing
    default_lang: str = Field(default="ru", env="DEFAULT_LANG")

    # Telegram Webhook security
    telegram_webhook_secret: str | None = Field(default=None, env="TELEGRAM_WEBHOOK_SECRET")
    
    # Web Interface
    web_username: str | None = Field(default=None, env="WEB_USERNAME")
    web_password: str | None = Field(default=None, env="WEB_PASSWORD")
    web_port: int = Field(default=8080, env="WEB_PORT")
    
    # External Services
    base_url: str | None = Field(default=None, env="BASE_URL")
    use_webhook: bool = Field(default=True, env="USE_WEBHOOK")
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )
    
    @property
    def admin_list(self) -> List[int]:
        """Parse admins string into list of integers."""
        if not self.admins.strip():
            return []
        return [int(x.strip()) for x in self.admins.split(",") if x.strip().isdigit()]
    
    @property
    def is_web_enabled(self) -> bool:
        """Check if web interface is enabled."""
        return bool(self.web_username and self.web_password)
    
settings = Settings()
