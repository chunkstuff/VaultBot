# core/services/user_service.py
import asyncio
from aiohttp import ClientResponseError
from collections import defaultdict
from errors.exceptions import UserAlreadyExists, UserLinkedToDifferentDiscord
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
        try:
            if await self.linker.user_exists(discord_id):
                jellyfin_id = await self.linker.get_jellyfin_user_id(discord_id)  # Updated method name
                jellyfin_user = await self.api.get_by_jellyfin_user_id(jellyfin_id)
                jellyfin_username = jellyfin_user['Name']
                raise UserAlreadyExists(jellyfin_username, linked=True)
            
            user = await self.get_user_by_jellyfin_username(discord_username)
            jellyfin_id = user.get("Id")
            linked_id = await self.get_jellyfin_user_id(discord_id)  # Updated method name
            
            if linked_id == jellyfin_id:
                logger.info("🔁 Jellyfin account already linked correctly.")
                raise UserAlreadyExists(discord_username, linked=True)
                
            if linked_id and linked_id != jellyfin_id:
                logger.warning("⚠️ Discord ID is linked to a different Jellyfin user.")
                raise UserLinkedToDifferentDiscord(discord_username)
                
            if not linked_id:
                logger.info(f"🔗 Linking unlinked Jellyfin user '{discord_username}' to Discord ID {discord_id}")
                await self.linker.link(discord_id, discord_username, jellyfin_id)
                raise UserAlreadyExists(discord_username, linked=False)
                
        except ClientResponseError as e:
            if e.status == 404:
                try:
                    logger.info(f"🆕 Creating new Jellyfin user '{discord_username}'")
                    new_user = await self.api.create_user(discord_username, password, is_admin)
                    await self.linker.link(discord_id, discord_username, new_user["Id"])
                    return new_user
                except Exception as inner_error:
                    if self.admin_notifier:
                        await self.admin_notifier.send_admin_alert(inner_error, context="User Creation/Link Failure")
                    raise
            raise
        except (UserAlreadyExists, UserLinkedToDifferentDiscord):
            raise
        except Exception as e:
            if self.admin_notifier:
                await self.admin_notifier.send_admin_alert(e, context="User Registration")
            raise

    # CORE JELLYFIN API METHODS (keep these)
    async def get_user_by_jellyfin_id(self, user_id: str) -> dict:
        return await self.api.get(f"Users/{user_id}")

    async def disable_vaultplus_user(self, user_id: str):
        return await self.api.disable_user(user_id)

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