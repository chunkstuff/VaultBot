# core/services/api.py 

import aiohttp
import discord
import traceback
import asyncio
from discord import Webhook
from discord.ext import commands
from aiohttp import ClientSession, ClientError, ServerTimeoutError, ClientResponseError, ClientConnectorError
from typing import Dict, List, Optional, Union, Any

from utils.logger_factory import setup_logger
from config.settings import settings

logger = setup_logger(__name__)

class JellyfinAPI:
    """Jellyfin API client with error handling and admin notifications."""
    
    def __init__(self, base_url: str, session: aiohttp.ClientSession, admin_notifier=None):
        """Initialize Jellyfin API client."""
        self.base_url = base_url.rstrip('/')
        self.session = session
        self.admin_notifier = admin_notifier

    async def _request(self, method: str, endpoint: str, discord: bool = False, **kwargs) -> Dict[str, Any]:
        """Make HTTP request with error handling. Returns JSON response."""
        url = endpoint if discord else f"{self.base_url}/{endpoint.lstrip('/')}"
        logger.debug(f"{method.upper()} {url} {f'with {kwargs}' if kwargs else ''}")
        
        try:
            async with self.session.request(method, url, **kwargs) as resp:
                resp.raise_for_status()
                if resp.status == 204:
                    return {}  # No content
                return await resp.json()

        except ClientConnectorError as e:
            # Connection issues (connection reset, DNS issues, etc.)
            logger.warning(f"🔌 Connection error for {method.upper()} {url}: {e}")
            if "Connection reset by peer" in str(e):
                logger.debug("Connection was reset by the server - this is usually temporary")
            # Don't alert admin for common connection issues
            raise
            
        except ServerTimeoutError as e:
            # Server timeout
            logger.warning(f"⏱️ Timeout error for {method.upper()} {url}: {e}")
            # Don't alert admin for timeouts
            raise
            
        except ClientResponseError as e:
            # HTTP errors (4xx, 5xx)
            if e.status >= 500:
                logger.error(f"🚨 Server error {e.status} for {method.upper()} {url}: {e}")
                # Alert admin for 5xx errors
                if self.admin_notifier:
                    await self.admin_notifier.send_admin_alert(
                        f"Jellyfin server error {e.status}: {e}", 
                        context=f"API {method.upper()} {endpoint}"
                    )
            else:
                logger.warning(f"⚠️ Client error {e.status} for {method.upper()} {url}: {e}")
            raise
            
        except asyncio.TimeoutError as e:
            # asyncio timeout
            logger.warning(f"⏱️ Request timeout for {method.upper()} {url}: {e}")
            raise
            
        except Exception as e:
            # Any other unexpected error
            trace = traceback.format_exc()
            logger.exception(f"❌ Unexpected API error for {method.upper()} {url}")
            if self.admin_notifier:
                await self.admin_notifier.send_admin_alert(trace, context=f"API {method.upper()} {endpoint}")
            raise

    async def get(self, endpoint: str) -> Dict[str, Any]:
        """Make GET request to Jellyfin API."""
        return await self._request("get", endpoint)

    async def post(self, endpoint: str, data: dict) -> Dict[str, Any]:
        """Make POST request to Jellyfin API with JSON data."""
        return await self._request("post", endpoint, json=data)

    async def delete(self, endpoint: str, **kwargs):
        """
        Make DELETE request to Jellyfin API with 404 handling - treats 404 as success since 
        'not found' during deletion means it's already deleted.
        """
        try:
            return await self._request("DELETE", endpoint, **kwargs)
        except ClientResponseError as e:
            if e.status == 404:
                # 404 during delete means already deleted - treat as success
                logger.debug(f"DELETE {endpoint} returned 404 - treating as success (already deleted)")
                return {}  # Return empty dict to indicate success
            # Re-raise other HTTP errors to trigger normal error handling
            raise

    async def create_user(self, username: str, password: str, is_admin: bool = False) -> Dict[str, Any]:
        """Create a new Jellyfin user account."""
        return await self.post("Users/New", {
            "Name": username,
            "Password": password,
            "IsAdmin": is_admin
        })

    async def reset_password(self, user_id: str) -> Dict[str, Any]:
        from utils.validation import generate_password
        new_password = generate_password()
        url =f"/Users/{user_id}/Password"
        try:
            await self.post(url, data={"NewPw": new_password})
            return {"success": True, "new_password": new_password}
        except Exception as e:
            logger.error(f"Failed to reset password for user {user_id}: {e}")
            return {"success": False, "error": str(e)}

    async def fetch_item_detail(self, item_id: str, user_id: str = settings.JELLYFIN_USER) -> Optional[Dict[str, Any]]:
        """Get detailed information about a media item. Returns None on error."""
        try:
            url = f"/Items/{item_id}?UserId={user_id}"
            return await self.get(url)
        except Exception as e:
            logger.error(f"❌ Failed to fetch item {item_id}: {e}")
            return None

    async def get_by_jellyfin_user_id(self, user_id: str) -> Dict[str, Any]:
        """Get user information by Jellyfin user ID."""
        return await self.get(f"Users/{user_id}")

    async def toggle_downloads(self, user_id: str, disabled: bool) -> Dict[str, Any]:
        """Enable or disable content downloading for a user."""
        payload = {
            f"userId": user_id,
            "EnableContentDownloading": not disabled,
            "AuthenticationProviderId": settings.VAULTPLUS_AUTH,
            "PasswordResetProviderId": settings.VAULTPLUS_PWRS,
        }
        action = "disabled" if disabled else "enabled"
        logger.info(f'Downloads {action} for {user_id}')
        return await self.post(f"/Users/{user_id}/Policy", data=payload)

    async def toggle_user_status(self, user_id: str, disabled: bool) -> Dict[str, Any]:
        """Enable or disable a user account."""
        payload = {
            f"userId": user_id,
            "IsDisabled": disabled,
            "AuthenticationProviderId": settings.VAULTPLUS_AUTH,
            "PasswordResetProviderId": settings.VAULTPLUS_PWRS,
        }
        action = "disabled" if disabled else "enabled"
        log_level = logger.warning if disabled else logger.info
        log_level(f'{user_id} has been {action}.')
        return await self.post(f"/Users/{user_id}/Policy", data=payload)

    async def get_sessions(self) -> List[Dict[str, Any]]:
        """Get active Jellyfin sessions. Returns empty list on network errors."""
        try:
            response = await self.get("/Sessions")
            if isinstance(response, list):
                return response
            elif isinstance(response, dict) and 'Items' in response:
                return response['Items']
            else:
                logger.warning(f"🤔 Unexpected sessions response format: {type(response)}")
                return []
                
        except (ClientConnectorError, ServerTimeoutError, asyncio.TimeoutError) as e:
            # Recoverable network errors - return empty list to continue operation
            logger.debug(f"🔌 Network error getting sessions (continuing with empty list): {e}")
            return []
            
        except ClientResponseError as e:
            if e.status >= 500:
                # Server errors - return empty list and continue
                logger.warning(f"🚨 Server error getting sessions (continuing with empty list): {e.status}")
                return []
            else:
                # Client errors (4xx) - might be auth issues, re-raise
                logger.error(f"⚠️ Client error getting sessions: {e.status} - {e}")
                raise
                
        except Exception as e:
            # Any other error - log and return empty list to prevent crash
            logger.error(f"❌ Unexpected error getting sessions (continuing with empty list): {e}")
            return []

    async def post_to_discord(self, embed: discord.Embed) -> Optional[discord.Message]:
        """Send embed to Discord webhook. Returns message on success, None on failure."""
        webhook_url = settings.WEBHOOKS.get("status")
        if not webhook_url:
            return None

        try:
            async with ClientSession() as session:
                webhook = Webhook.from_url(webhook_url, session=session)
                return await webhook.send(embed=embed, wait=True)
        except Exception as e:
            logger.warning(f"[SessionMonitor] Webhook send failed: {e}")
            return None