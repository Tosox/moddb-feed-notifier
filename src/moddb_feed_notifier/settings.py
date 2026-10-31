from __future__ import annotations

import re
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlparse

import apprise
from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

MessageFormat = Literal["markdown", "html", "text", "discord"]

DISCORD_WEBHOOK_RE = re.compile(r"^https://(?:\w+\.)?discord(?:app)?\.com/api/webhooks/\d+/[\w-]+/?$")
MODDB_HOSTS = {"moddb.com", "www.moddb.com"}


def is_discord_webhook(url: str) -> bool:
    return bool(DISCORD_WEBHOOK_RE.match(url))


class TemplateSettings(BaseSettings):
    """The part of the configuration needed to render messages, e.g. for --preview."""

    model_config = SettingsConfigDict(env_prefix="MFN_", env_file=".env", extra="ignore")

    notify_url: SecretStr | None = None
    message_format: MessageFormat | None = None
    template_dir: Path | None = None

    @field_validator("message_format", mode="before")
    @classmethod
    def lower_message_format(cls, value: object) -> object:
        return value.lower() if isinstance(value, str) else value

    @field_validator("template_dir")
    @classmethod
    def check_template_dir(cls, value: Path | None) -> Path | None:
        if value is not None and not value.is_dir():
            raise ValueError(f"'{value}' is not a directory")
        return value

    @model_validator(mode="after")
    def default_message_format(self) -> TemplateSettings:
        # Discord webhooks get rich embeds by default, everything else Markdown
        if self.message_format is None:
            url = self.notify_url.get_secret_value() if self.notify_url else ""
            self.message_format = "discord" if is_discord_webhook(url) else "markdown"
        return self


class Settings(TemplateSettings):
    """All configuration, read from environment variables (prefix MFN_) or a .env file."""

    page: str
    types: Annotated[list[str], NoDecode] = Field(default=["addons"], min_length=1)
    notify_url: SecretStr
    interval: int = Field(default=30, ge=1)
    max_items: int = Field(default=10, ge=1)
    state_dir: Path = Path("state")
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    @field_validator("page")
    @classmethod
    def check_page(cls, value: str) -> str:
        url = urlparse(value.strip())
        if url.scheme not in ("http", "https") or url.netloc not in MODDB_HOSTS:
            raise ValueError("must be a ModDB URL, e.g. https://www.moddb.com/mods/stalker-anomaly")
        return url.path.strip("/")

    @field_validator("types", mode="before")
    @classmethod
    def split_types(cls, value: object) -> object:
        if isinstance(value, str):
            return list(dict.fromkeys(t.lower() for t in re.split(r"[,;\s]+", value) if t))
        return value

    @field_validator("types")
    @classmethod
    def check_types(cls, value: list[str]) -> list[str]:
        invalid = [t for t in value if not re.fullmatch(r"[a-z]+", t)]
        if invalid:
            raise ValueError(f"invalid feed type(s) {', '.join(invalid)}, use names like addons, articles, videos")
        return value

    @field_validator("log_level", mode="before")
    @classmethod
    def upper_log_level(cls, value: object) -> object:
        return value.upper() if isinstance(value, str) else value

    @field_validator("notify_url")
    @classmethod
    def check_notify_url(cls, value: SecretStr) -> SecretStr:
        url = value.get_secret_value()
        if is_discord_webhook(url):
            return value
        apobj = apprise.Apprise()
        if not apobj.add(url) or len(apobj) != 1:
            raise ValueError("must be exactly one valid Apprise URL, see https://appriseit.com/services/")
        return value

    @model_validator(mode="after")
    def check_discord_format(self) -> Settings:
        if self.message_format == "discord" and not is_discord_webhook(self.notify_url.get_secret_value()):
            raise ValueError("MFN_MESSAGE_FORMAT=discord requires a Discord webhook URL as MFN_NOTIFY_URL")
        return self

    def feed_url(self, feed_type: str) -> str:
        path = f"{self.page}/{feed_type}" if self.page else feed_type
        return f"https://rss.moddb.com/{path}/feed/rss.xml"

    @property
    def page_url(self) -> str:
        return f"https://www.moddb.com/{self.page}"
