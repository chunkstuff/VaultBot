import aiohttp
import discord
import traceback
from discord import Webhook
from discord.ext import commands
from aiohttp import ClientSession


from utils.logger_factory import setup_logger
from config.settings import settings

logger = setup_logger(__name__)

class JellyfinAPI:
    def __init__(self, base_url: str, session: dict, admin_notifier=None):
        self.base_url = base_url.rstrip('/')
        self.session = session
        self.admin_notifier = admin_notifier

    async def _request(self, method: str, endpoint: str, discord: bool = False, **kwargs) -> dict:
        url = endpoint if discord else f"{self.base_url}/{endpoint.lstrip('/')}"
        logger.debug(f"{method.upper()} {url} {f'with {kwargs}' if kwargs else ''}")
        try:
            async with self.session.request(method, url, **kwargs) as resp:
                resp.raise_for_status()
                if resp.status == 204:
                    return {}  # No content
                return await resp.json()

        except Exception:
            trace = traceback.format_exc()
            logger.exception(f"❌ API {method.upper()} {url} failed")
            if self.admin_notifier:
                await self.admin_notifier.send_admin_alert(trace, context=f"API {method.upper()} {endpoint}")
            raise

    async def get(self, endpoint: str) -> dict:
        return await self._request("get", endpoint)

    async def post(self, endpoint: str, data: dict) -> dict:
        return await self._request("post", endpoint, json=data)

    async def delete(self, endpoint: str, **kwargs):
        return await self._request("DELETE", endpoint, **kwargs)

    async def create_user(self, username: str, password: str, is_admin: bool = False):
        return await self.post("Users/New", {
            "Name": username,
            "Password": password,
            "IsAdmin": is_admin
        })

    async def fetch_item_detail(self, item_id: str, user_id: str = settings.JELLYFIN_USER):
        try:
            url = f"/Items/{item_id}?UserId={user_id}"
            return await self.get(url)
        except Exception as e:
            # Optional: log the error for visibility
            logger.error(f"❌ Failed to fetch item {item_id}: {e}")
            return None

    async def get_by_jellyfin_user_id(self, user_id: str):
        return await self.get(f"Users/{user_id}")

    async def disable_downloads(self, user_id: str):
        payload = {
                    f"userId": user_id, 
                    "EnableContentDownloading": False,
                    "AuthenticationProviderId": settings.VAULTPLUS_AUTH,
                    "PasswordResetProviderId": settings.VAULTPLUS_PWRS,
                }
        return await self.post(f"Users/{user_id}/Policy", data=payload)

    async def disable_user(self, user_id: str):
        payload = {
                    f"userId": user_id,
                    "IsDisabled": True,
                    "AuthenticationProviderId": settings.VAULTPLUS_AUTH,
                    "PasswordResetProviderId": settings.VAULTPLUS_PWRS,
                }
        logger.warning(f'{user_id} has been disabled.')
        return await self.post(f"/Users/{user_id}/Policy", data=payload)

    async def get_sessions(self):
        return await self.get("/Sessions")

    async def post_to_discord(self, embed: discord.Embed) -> discord.Message | None: 
        webhook_url = settings.WEBHOOKS.get("status")
        if not webhook_url:
            return None

        async with ClientSession() as session:
            webhook = Webhook.from_url(webhook_url, session=session)
            try:
                return await webhook.send(embed=embed, wait=True)
            except Exception as e:
                print(f"[SessionMonitor] Webhook send failed: {e}")
                return None
