import aiohttp
import aiofiles
import os
import traceback
from utils.logger_factory import setup_logger

logger = setup_logger(__name__)

class AvatarService:
    def __init__(self, navigator, admin_notifier=None):
        self.navigator = navigator
        self.admin_notifier = admin_notifier

    def force_discord_image_size(self, url: str, size: int = 256) -> str:
        from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        query["size"] = [str(size)]
        return urlunparse(parsed._replace(query=urlencode(query, doseq=True)))

    async def upload_avatar(self, user_id: str, image_url: str, username: str, password: str) -> bool:
        image_url = self.force_discord_image_size(image_url, size=256)
        logger.info(f"📥 Downloading avatar from: {image_url}")

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(image_url) as resp:
                    resp.raise_for_status()
                    image_bytes = await resp.read()
        except Exception as e:
            if self.admin_notifier:
                await self.admin_notifier.send_admin_alert(e, context="Avatar Download")
            raise

        temp_path = f"{username}_{user_id}.jpg"
        try:
            async with aiofiles.open(temp_path, "wb") as f:
                await f.write(image_bytes)

            logger.info("⚡ Uploading via navigator...")
            await self.navigator.upload_avatar(username, password, user_id, temp_path)
            logger.info("✅ Avatar uploaded.")
            return True

        except Exception as e:
            if self.admin_notifier:
                await self.admin_notifier.send_admin_alert(e, context="Avatar Upload")
            raise

        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

        return False