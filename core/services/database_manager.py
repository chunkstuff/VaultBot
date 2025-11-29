from db.jellyfin_db import VaultPulseDB
from db.user_links_db import UserLinksDB
from db.database_link_map import HotLinkManager
from core.services.user_sessions import UserSessions
from config.settings import settings

class DatabaseManager:
    def __init__(
        self, 
        vault_pulse_path: str = None,
        user_links_path: str = None
    ):
        vault_pulse_path = vault_pulse_path or f"{settings.DB_PATH}/vaultpulse.db"
        user_links_path = user_links_path or f"{settings.DB_PATH}/user_links.db"
        
        self.vault_pulse_db = VaultPulseDB(db_path=vault_pulse_path)
        self.user_links_db = UserLinksDB(db_path=user_links_path)
        self.user_linker = HotLinkManager(self.user_links_db)
        self.user_sessions = UserSessions(self.vault_pulse_db)

    async def connect_all(self):
        await self.vault_pulse_db.connect()
        await self.vault_pulse_db.init_schema()
        await self.user_links_db.connect()

    async def close_all(self):
        await self.vault_pulse_db.close()
        await self.user_links_db.close()
