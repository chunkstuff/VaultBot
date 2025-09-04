# db/user_sessions.py

from db.jellyfin_db import VaultPulseDB
from utils.logger_factory import setup_logger

logger = setup_logger(__name__)


class UserSessions:
    def __init__(self, user_session_db: VaultPulseDB):
        self.user_session_db = user_session_db

    async def flush_buffer(self, hourly_buffer: dict[tuple[str, str, str], int]) -> int:
        return await self.user_session_db.flush_hourly_buffer(hourly_buffer)
