from db.user_links_db import UserLinksDB
from utils.logger_factory import setup_logger

logger = setup_logger(__name__)

class UserLinker:
    def __init__(self, user_links_db: UserLinksDB):
        self.user_links_db = user_links_db

    async def get_all_links(self) -> list[dict]:
        return await self.user_links_db.get_all_links()

    async def get_linked_jellyfin_id(self, discord_id: str) -> str | None:
        logger.debug(f"🔎 Checking DB for Jellyfin link for Discord ID {discord_id}")
        return await self.user_links_db.get_jellyfin_user(discord_id)

    async def user_exists(self, discord_id: str) -> bool:
        return await self.user_links_db.is_discord_user_linked(discord_id)

    async def link(self, discord_id: str, discord_username: str, jellyfin_id: str) -> None:
        logger.info(f"🔗 Linking Discord '{discord_username}' ({discord_id}) to Jellyfin ID '{jellyfin_id}'")
        await self.user_links_db.link_user(discord_id, discord_username, jellyfin_id)
