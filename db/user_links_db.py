import aiosqlite
from pathlib import Path
from utils.logger_factory import setup_logger

logger = setup_logger(__name__)

class UserLinksDB:
    def __init__(self, db_path: str = "db/user_links.db"):
        self.db_path = str(Path(db_path))
        self._conn: aiosqlite.Connection | None = None

    async def connect(self):
        self._conn = await aiosqlite.connect(self.db_path)
        self._conn.row_factory = aiosqlite.Row
        await self._initialize()
        logger.info(f"🔗 Connected to User Links DB at {self.db_path}")

    async def close(self):
        if self._conn:
            await self._conn.close()
            logger.info("🔌 User Links DB connection closed")

    async def _initialize(self):
        await self._conn.execute("""
            CREATE TABLE IF NOT EXISTS user_links (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                discord_user_id TEXT UNIQUE NOT NULL,
                discord_username TEXT NOT NULL,
                jellyfin_user_id TEXT UNIQUE NOT NULL
            )
        """)
        
        # Add index creation following VaultPulseDB pattern
        await self._create_indexes()
        
        await self._conn.commit()
        logger.info("[DB] Table 'user_links' ensured.")

    async def _create_indexes(self):
        """Create indexes following VaultPulseDB pattern"""
        await self._conn.executescript("""
        CREATE INDEX IF NOT EXISTS idx_user_links_jellyfin_id ON user_links(jellyfin_user_id);
        CREATE INDEX IF NOT EXISTS idx_user_links_discord_id ON user_links(discord_user_id);
        """)
        logger.info("🔢 UserLinksDB indexes created or verified")

    async def is_discord_user_linked(self, discord_user_id: str) -> bool:
        result = await self.get_jellyfin_user(discord_user_id)
        return result is not None

    async def link_user(self, discord_user_id: str, discord_username: str, jellyfin_user_id: str):
        logger.info(f"[DB] Linking Discord '{discord_username}' ({discord_user_id}) to Vault+ ID '{jellyfin_user_id}'")
        await self._conn.execute("""
            INSERT INTO user_links (discord_user_id, discord_username, jellyfin_user_id)
            VALUES (?, ?, ?)
            ON CONFLICT(discord_user_id) DO UPDATE SET
                discord_username = excluded.discord_username,
                jellyfin_user_id = excluded.jellyfin_user_id
        """, (discord_user_id, discord_username, jellyfin_user_id))
        await self._conn.commit()
        logger.info("[DB] Link committed.")

    
    async def get_all_links(self) -> list[dict]:
        query = "SELECT discord_user_id, discord_username, jellyfin_user_id FROM user_links"
        async with self._conn.execute(query) as cursor:
            return [
                {
                    "discord_user_id": row[0],
                    "discord_username": row[1],
                    "jellyfin_user_id": row[2],
                }
                async for row in cursor
            ]

    async def get_jellyfin_user(self, discord_user_id: str) -> str | None:
        logger.debug(f"[DB] Fetching Vault+ ID for Discord user ID '{discord_user_id}'")
        async with self._conn.execute("SELECT jellyfin_user_id FROM user_links WHERE discord_user_id = ?", (discord_user_id,)) as cur:
            row = await cur.fetchone()
            if row:
                logger.debug(f"[DB] Found Vault+ ID: {row['jellyfin_user_id']}")
                return row['jellyfin_user_id']
            logger.warning(f"[DB] No entry found for Discord ID '{discord_user_id}'")
            return None
