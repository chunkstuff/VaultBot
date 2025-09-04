import discord
from core.services.api import JellyfinAPI
from core.services.user_service import UserService
from core.services.avatar_service import AvatarService

class JellyfinClient:
    def __init__(self, api: JellyfinAPI, users: UserService, avatars: AvatarService):
        self.api = api
        self.users = users
        self.avatars = avatars

    async def get_sessions(self):
        return await self.api.get_sessions()

    async def post_session_info(self, embed: discord.Embed):
        return await self.api.post_to_discord(embed)
