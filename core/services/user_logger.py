import json
from pathlib import Path
from datetime import datetime
import aiofiles
import asyncio
from config.settings import settings

LOG_PATH = Path(settings.REGISTRATION_LOG_PATH)

async def log_registered_user(discord_id: str, discord_username: str, jellyfin_username: str, email: str):
    entry = {
        "timestamp": datetime.utcnow().isoformat(),
        "discord_id": discord_id,
        "discord_username": discord_username,
        "jellyfin_username": jellyfin_username,
        "email": email,
    }

    async with aiofiles.open(LOG_PATH, mode="a") as f:
        await f.write(json.dumps(entry) + "\n")
