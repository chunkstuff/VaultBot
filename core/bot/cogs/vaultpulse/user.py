# core/bot/cogs/vaultpulse/user.py
from datetime import datetime
from typing import Any

class UserSync:
    def __init__(self, bot):
        self.bot = bot
    
    async def prepare_user_rows(self, buffer, cached_users: list[dict[str, Any]]) -> list[tuple]:
        """
        Build upsert rows from buffer:
        (user_id, discord_id, jellyfin_username, discord_username, registered_at, last_seen)
        """
        now = datetime.utcnow().isoformat()
        user_ids = buffer.get_user_ids()
        user_map = {u["Id"]: u for u in cached_users}
        rows = []
        
        for user_id in user_ids:
            jf_user = user_map.get(user_id, {})
            jellyfin_username = jf_user.get("Name", "unknown")
            registered_at = jf_user.get("DateCreated") or now

            info = await self.bot.link_map.get_discord_info(user_id)
            discord_id, discord_username = info if info else (None, "Unknown#0000")
            
            rows.append((
                user_id,
                discord_id,
                jellyfin_username,
                discord_username,
                registered_at,
                now,
            ))
        return rows