# core/services/user_service.py
import asyncio
from aiohttp import ClientResponseError
from collections import defaultdict
from errors.exceptions import (
    DiscordAlreadyLinkedSameUsername,
    DiscordAlreadyLinkedDifferentUsername,
    UsernameExistsUnlinked,
    UsernameTaken
)
from utils.logger_factory import setup_logger

logger = setup_logger(__name__)

class UserService:
    def __init__(self, api, database, admin_notifier=None):
        self.api = api
        self.linker = database.user_linker  # HotLinkManager instance
        self.sessions = database.user_sessions
        self.admin_notifier = admin_notifier
        self.user_locks = defaultdict(asyncio.Lock)

    async def register_user(self, discord_id: str, discord_username: str, password: str, is_admin: bool = False) -> dict:
        """
        Args:
            discord_id: Discord user ID
            discord_username: Requested Jellyfin username (NOT their Discord username)
            password: Password for the account
        """
        try:
            # Check if Discord ID is already linked
            existing_jellyfin_id = await self.linker.get_jellyfin_user_id(discord_id)
            if existing_jellyfin_id:
                jellyfin_user = await self.api.get_by_jellyfin_user_id(existing_jellyfin_id)
                existing_username = jellyfin_user['Name']
                
                if existing_username == discord_username:
                    raise DiscordAlreadyLinkedSameUsername(existing_username)
                else:
                    raise DiscordAlreadyLinkedDifferentUsername(existing_username, discord_username)
            
            # Discord ID not linked - check if username exists
            try:
                user = await self.get_user_by_jellyfin_username(discord_username)
                jellyfin_id = user.get("Id")
                
                # Check if this Jellyfin account is linked
                jellyfin_discord_info = await self.linker.get_discord_info(jellyfin_id)
                
                if jellyfin_discord_info:
                    raise UsernameTaken(discord_username)
                else:
                    # Username exists but unlinked - link it
                    await self.linker.link(discord_id, discord_username, jellyfin_id)
                    raise UsernameExistsUnlinked(discord_username)
            
            except ClientResponseError as e:
                if e.status == 404:
                    # Username doesn't exist - create new user
                    new_user = await self.api.create_user(discord_username, password, is_admin)
                    await self.linker.link(discord_id, discord_username, new_user["Id"])
                    return new_user
                raise
        
        except (DiscordAlreadyLinkedSameUsername, DiscordAlreadyLinkedDifferentUsername, 
                UsernameExistsUnlinked, UsernameTaken):
            raise
        except Exception as e:
            if self.admin_notifier:
                await self.admin_notifier.send_admin_alert(e, context="User Registration")
            raise

    # CORE JELLYFIN API METHODS (keep these)
    async def get_user_by_jellyfin_id(self, user_id: str) -> dict:
        return await self.api.get(f"Users/{user_id}")

    async def disable_vaultplus_user(self, user_id: str) -> dict:
        """Disable a user account."""
        return await self.api.toggle_user_status(user_id, disabled=True)

    async def enable_vaultplus_user(self, user_id: str) -> dict:
        """Enable a user account."""
        return await self.api.toggle_user_status(user_id, disabled=False)

    async def disable_downloads(self, user_id: str) -> dict:
        """Disable content downloading for a user."""
        return await self.api.toggle_downloads(user_id, disabled=True)

    async def enable_downloads(self, user_id: str) -> dict:
        """Enable content downloading for a user."""
        return await self.api.toggle_downloads(user_id, disabled=False)

    async def get_user_by_jellyfin_username(self, username: str) -> dict:
        users = await self.api.get("Users")
        for user in users:
            if user.get("Name") == username:
                return user
        raise ClientResponseError(request_info=None, history=None, status=404, message="User not found", headers=None)

    # SIMPLIFIED USER LINKING METHODS (delegate to HotLinkManager)
    async def get_jellyfin_user_id(self, discord_id: str) -> str | None:
        """Get Jellyfin user ID for a Discord user"""
        return await self.linker.get_jellyfin_user_id(discord_id)

    async def get_jellyfin_user_by_discord_id(self, discord_id: str) -> dict | None:
        """Get full Jellyfin user object for a Discord user"""
        jellyfin_id = await self.get_jellyfin_user_id(discord_id)
        if not jellyfin_id:
            return None
        return await self.get_user_by_jellyfin_id(jellyfin_id)