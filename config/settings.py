import os
import json
import logging
import discord
from pathlib import Path
from typing import Annotated

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)
CONFIG_PATH = Path("config/config.json")
ENV_FILE = os.getenv("ENV_FILE_PATH", "config/secrets.env")


class Settings(BaseSettings):
    # Test mode flag
    TEST_MODE: Annotated[bool, Field(description="Enable test mode (relaxed guild checks)")] = False

    # Jellyfin config
    JELLYFIN_URL: Annotated[str, Field(description="Base URL for the Jellyfin server")]
    API_KEY: Annotated[str, Field(description="API key for Jellyfin")]
    JELLYFIN_USER: Annotated[str, Field(description="UserId for retreiving Items")]
    JELLYFIN_SERVER_ID: Annotated[str, Field(description="Server ID for Jellyfin")]
    DEVICE: Annotated[str, Field(description="Device name registered with Jellyfin")]
    DEVICE_ID: Annotated[str, Field(description="Unique device ID for Jellyfin access")]
    APP_NAME: Annotated[str, Field(description="App name for Emby/Jellyfin authentication")]
    APP_VERSION: Annotated[str, Field(description="Version of the app used in headers")]
    VAULTBOT_ID: Annotated[str, Field(description="Jellyfin user id for VaultBot")]
    VAULTPLUS_AUTH: Annotated[str, Field(description="Requirement for elevated API calls")]
    VAULTPLUS_PWRS: Annotated[str, Field(description="Requirement to reset passwords via API")]

    # Discord auth
    DISCORD_TOKEN: Annotated[str, Field(description="Token for Discord bot authentication")]

    # Discord channels, roles & IDs
    GUILD_ID: Annotated[int, Field(description="Main Discord guild/server ID")]
    ADMIN_CHANNEL: Annotated[int, Field(description="Discord channel ID to send admin alerts")]
    REGISTER_CHANNEL: Annotated[int, Field(description="Discord channel ID to send the persistent registration embed")]
    LOGIN_CHANNEL: Annotated[int, Field(description="Discord channel ID to send the persistent login embed")]
    DASHBOARD_CHANNEL: Annotated[int, Field(description="Discord channel ID to send statistics dashboard")]
    WORSE_PLUS_CHANNEL: Annotated[int, Field(description="Discord channel ID to send makemeworseplus embed")]
    NETWORK_CHANNEL: Annotated[int, Field(description="Discord channel ID to send playlist notifications")]
    VAULTPLUS_ROLE: Annotated[int, Field(description="Discord role ID to apply to Vault+ registered users")]
    SUBSCRIBE_ROLE: Annotated[int, Field(description="Discord role ID to apply to Vault subscribers")]
    STAFF_ROLE: Annotated[int, Field(description="Discord role ID for Staff members")]
    JUNIOR_STAFF_ROLE: Annotated[int, Field(description="Discord role ID for Junior Staff members")]
    DEVELOPER_ID: Annotated[int, Field(description="Discord user ID of the developer for tagging/errors")]
    OWNER_ID: Annotated[int, Field(description="Discord user ID of the server for admin validation")]

    # Discord Webhook
    WEBHOOK_STATUS_URL: Annotated[str, Field(description="Discord webhook url to send status updates to")]

    # Email (SMTP)
    SMTP_SERVER: Annotated[str, Field(description="SMTP server hostname or IP address")]
    SMTP_PORT: Annotated[int, Field(description="SMTP server port (e.g., 587 for TLS)")]
    SMTP_USERNAME: Annotated[str, Field(description="Username for SMTP authentication")]
    SMTP_PASSWORD: Annotated[str, Field(description="Password or token for SMTP authentication")]
    EMAIL_FROM: Annotated[str, Field(description="Email address used in the From header")]

    # Local API
    SUBSCRIPTION_API_BASE_URL: Annotated[str, Field(description="Base URL for subscription API endpoints")]

    # Paths
    DB_PATH: Annotated[str, Field(description="Path for database files")]
    LOG_PATH: Annotated[str, Field(description="Path for application logs")]
    ERROR_SCREENSHOT_PATH: Annotated[str, Field(description="Path for error screenshots")]
    REGISTRATION_LOG_PATH: Annotated[str, Field(description="Path for registration log")]
    MISSING_TAGS_PATH: Annotated[str, Field(description="Path for missing tags metrics")]

    @property
    def HEADERS(self) -> dict:
        return {
            "X-Emby-Token": self.API_KEY,
            "X-Emby-Authorization": (
                f"MediaBrowser Client={self.APP_NAME}, "
                f"Device={self.DEVICE}, "
                f"DeviceId={self.DEVICE_ID}, "
                f"Version={self.APP_VERSION}"
            ),
            "Content-Type": "application/json",
        }

    @property
    def WEBHOOKS(self) -> dict:
        return {
            "status": self.WEBHOOK_STATUS_URL
        }

    @property
    def SUBSCRIPTION_ENDPOINTS(self) -> dict:
        return {
            "expired": f"{self.SUBSCRIPTION_API_BASE_URL}/api/expired-subscribers",
            "active": f"{self.SUBSCRIPTION_API_BASE_URL}/api/newly-active-subscribers"
        }

    @property 
    def config(self) -> dict:
        try:
            if CONFIG_PATH.exists():
                with open(CONFIG_PATH, "r") as f:
                    return json.load(f)
        except Exception as e:
            logger.warning(f"⚠️ Failed to load config: {e}")
        return {}

    def get_embed_config(self, key: str) -> dict:
        return self.config.get(key, {})

    def get_register_embeds(self) -> list[dict]:
        return self.get_embed_config("register_embed").get("messages", [])

    def save_embed_config(self, key: str, channel_id: int, message_id: int):
        config = self.config
        embed = config.get(key, {})
        embed.update({"channel_id": channel_id, "message_id": message_id})
        config[key] = embed
        self._write_config(config)

    def update_embed_config(self, key: str, **updates):
        config = self.config
        embed = config.get(key, {})
        embed.update(updates)
        config[key] = embed
        self._write_config(config)

    def save_register_embeds(self, messages: list[discord.Message]):
        """Save multiple register embed messages persistently."""
        config = self.config
        register_cfg = config.get("register_embed", {})
        register_cfg["messages"] = [
            {"channel_id": m.channel.id, "message_id": m.id} for m in messages
        ]
        config["register_embed"] = register_cfg
        self._write_config(config)

    def save_login_embed(self, channel_id: int, message_id: int):
        config = self.config
        login_cfg = config.get("login_embed", {})
        login_cfg.update({"channel_id": channel_id, "message_id": message_id})
        config["login_embed"] = login_cfg
        self._write_config(config)

    def save_worse_embed(self, channel_id: int, message_id: int):
        config = self.config
        worse_cfg = config.get("makeworse_embed", {})
        worse_cfg.update({"channel_id": channel_id, "message_id": message_id})
        config["makeworse_embed"] = worse_cfg
        self._write_config(config)

    def _write_config(self, config: dict):
        try:
            CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
            with open(CONFIG_PATH, "w") as f:
                json.dump(config, f, indent=2)
            logger.info("✅ Config file updated.")
        except Exception:
            logger.exception("❌ Failed to write config.json")

    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8"
    )


settings = Settings()