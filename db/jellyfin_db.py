import aiosqlite
import asyncio
from pathlib import Path

from config.time_helpers import format_ticks
from utils.logger_factory import setup_logger

logger = setup_logger(__name__)

class VaultPulseDB:
    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        self._conn: aiosqlite.Connection | None = None

    async def connect(self):
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)  # ✅ ensure dir
        self._conn = await aiosqlite.connect(self.db_path)
        self._conn.row_factory = aiosqlite.Row
        logger.info(f"🔗 Connected to VaultPulseDB at {self.db_path}")

    async def init_schema(self):
        if not self._conn:
            await self.connect()

        await self._create_users_table()
        await self._create_items_table()
        await self._create_listening_tables()
        await self._create_user_playlists_table()
        await self._create_playlist_items_table()
        await self._create_playlist_tracking_tables()
        await self._create_indexes()

        await self._conn.commit()
        logger.info("📐 VaultPulseDB schema initialized")

    async def _create_users_table(self):
        await self._conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            discord_id INTEGER,
            jellyfin_username TEXT,
            discord_username TEXT,
            registered_at TIMESTAMP,
            last_seen TIMESTAMP,
            is_active BOOLEAN DEFAULT 1
        );
        """)
        logger.info("✅ users table created or verified")

    async def _create_items_table(self):
        await self._conn.execute("""
        CREATE TABLE IF NOT EXISTS items (
            id TEXT PRIMARY KEY,
            title TEXT,
            type TEXT,
            collection TEXT,
            category TEXT,
            last_fetched TIMESTAMP,
            metadata_json TEXT
        );
        """)
        logger.info("✅ items table created or verified")

    async def _create_listening_tables(self):
        await self._conn.executescript("""
        CREATE TABLE IF NOT EXISTS listening_stats (
            user_id TEXT NOT NULL,
            item_id TEXT NOT NULL,
            total_ticks INTEGER DEFAULT 0,
            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (user_id, item_id)
        );

        CREATE TABLE IF NOT EXISTS listening_hourly (
            user_id TEXT NOT NULL,
            item_id TEXT NOT NULL,
            hour_start TIMESTAMP NOT NULL,
            ticks INTEGER DEFAULT 0,
            PRIMARY KEY (user_id, item_id, hour_start)
        );
        """)
        logger.info("✅ listening_stats and listening_hourly tables created or verified")

    async def _create_user_playlists_table(self):
        await self._conn.execute("""
        CREATE TABLE IF NOT EXISTS user_playlists (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            discord_id TEXT NOT NULL,
            playlist_name TEXT,
            generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            playlist_items TEXT NOT NULL,
            num_files INTEGER NOT NULL,
            collections TEXT,
            tags TEXT,
            is_expired BOOLEAN DEFAULT 0
        );
        """)
        logger.info("✅ user_playlists table created or verified")

    async def _create_playlist_items_table(self):
        await self._conn.execute("""
        CREATE TABLE IF NOT EXISTS playlist_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_playlist_id INTEGER NOT NULL,        -- FK to user_playlists.id
            jf_playlist_id TEXT,                      -- Jellyfin playlist GUID (optional but handy)
            item_id TEXT NOT NULL,                    -- Jellyfin item Id
            order_index INTEGER NOT NULL,             -- 0-based order in the playlist
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_playlist_id) REFERENCES user_playlists(id)
                ON DELETE CASCADE
        );
        """)
        logger.info("✅ playlist_items table created or verified")

    async def _create_playlist_tracking_tables(self):
        # Tracks a user's active playlist session & current index
        await self._conn.execute("""
        CREATE TABLE IF NOT EXISTS playlist_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            discord_id TEXT NOT NULL,
            user_playlist_id INTEGER NOT NULL,   -- FK to user_playlists.id
            jf_playlist_id TEXT,                 -- Jellyfin playlist GUID (optional cache)
            started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            current_index INTEGER DEFAULT 0,     -- 0-based track pointer
            is_confirmed BOOLEAN DEFAULT 0,      -- confirmed by moving from track 0->1
            is_complete  BOOLEAN DEFAULT 0,      -- whole playlist finished
            FOREIGN KEY (user_playlist_id) REFERENCES user_playlists(id) ON DELETE CASCADE
        );
        """)
        logger.info("✅ playlist_sessions table created or verified")
        
        # Track per-file completions when listening *in order* within an active session
        await self._conn.execute("""
        CREATE TABLE IF NOT EXISTS playlist_file_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            playlist_session_id INTEGER NOT NULL,  -- FK to playlist_sessions.id
            item_id TEXT NOT NULL,                 -- Jellyfin item id
            order_index INTEGER NOT NULL,          -- which position in the playlist
            completed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            listen_duration_seconds REAL DEFAULT 0,
            FOREIGN KEY (playlist_session_id) REFERENCES playlist_sessions(id) ON DELETE CASCADE
        );
        """)
        logger.info("✅ playlist_file_events table created or verified")


    async def _create_indexes(self):
        await self._conn.executescript("""
        CREATE INDEX IF NOT EXISTS idx_user_playlists_discord_id ON user_playlists(discord_id);
        CREATE INDEX IF NOT EXISTS idx_users_discord_id ON users(discord_id);
        CREATE INDEX IF NOT EXISTS idx_items_collection ON items(collection);
        CREATE INDEX IF NOT EXISTS idx_items_category ON items(category);
        CREATE INDEX IF NOT EXISTS idx_listening_stats_user_id ON listening_stats(user_id);
        CREATE INDEX IF NOT EXISTS idx_listening_hourly_user_id ON listening_hourly(user_id);
        CREATE INDEX IF NOT EXISTS idx_playlist_items_user_playlist_id ON playlist_items(user_playlist_id);
        CREATE INDEX IF NOT EXISTS idx_playlist_items_jf_playlist_id ON playlist_items(jf_playlist_id);
        CREATE INDEX IF NOT EXISTS idx_playlist_sessions_discord_active ON playlist_sessions(discord_id, is_complete, last_seen);
        CREATE INDEX IF NOT EXISTS idx_playlist_file_events_session ON playlist_file_events(playlist_session_id);
        """)
        logger.info("🔢 Indexes created or verified")



    async def flush_hourly_buffer(self, hourly_buffer: dict[tuple[str, str, str], int]) -> int:
        """
        Writes the hourly tick totals to the database.

        :param hourly_buffer: {(user_id, item_id, hour_start): ticks}
        """
        if not self._conn:
            await self.connect()

        sql = """
        INSERT INTO listening_hourly (user_id, item_id, hour_start, ticks)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(user_id, item_id, hour_start)
        DO UPDATE SET ticks = ticks + excluded.ticks
        """

        param_list = [
            (user_id, item_id, hour_start, ticks)
            for (user_id, item_id, hour_start), ticks in hourly_buffer.items()
        ]

        count = await self.execute_many(sql, param_list)
        logger.info(f"🕒 Flushed {count} hourly listening rows to VaultPulse")
        return count

    async def upsert_users(self, user_details: list[tuple]) -> int:
        sql = """
        INSERT INTO users (
            id, discord_id, jellyfin_username, discord_username, registered_at, last_seen
        ) VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            discord_id = excluded.discord_id,
            discord_username = excluded.discord_username,
            last_seen = excluded.last_seen,
            is_active = 1
        """
        count =  await self.execute_many(sql, user_details)
        logger.info(f"👤 Flushed {count} hourly user rows to VaultPulse")
        return count

    async def upsert_items(self, item_rows: list[tuple]) -> int:
        """
        Upserts media item rows:
        (id, title, type, last_fetched, metadata_json)
        """
        sql = """
        INSERT INTO items (id, title, type, collection, category, last_fetched, metadata_json)
        VALUES (?, ?, ?, ?, ?, ? ,?)
        ON CONFLICT(id) DO UPDATE SET
            title = excluded.title,
            type = excluded.type,
            last_fetched = excluded.last_fetched,
            metadata_json = excluded.metadata_json
        """
        count =  await self.execute_many(sql, item_rows)
        logger.info(f"📋 Flushed {count} hourly item rows to VaultPulse")
        return count

    async def get_top_listeners_text(self, link_map) -> str:
        sql = """
        SELECT user_id, SUM(ticks) as total
        FROM listening_hourly
        GROUP BY user_id
        ORDER BY total DESC
        LIMIT 3
        """
        rows = await self.query(sql)

        lines = []
        for i, row in enumerate(rows, 1):
            uid = row["user_id"]
            ticks = row["total"]

            info = await link_map.get_discord_info(uid)
            if info:
                mention = f"<@{info[0]}>"
            else:
                mention = "Unknown"
                
            lines.append(f"{i}. {mention} – `{format_ticks(ticks)}`")

        return "**🏆 Top 3 listeners:**\n" + "\n".join(lines)

    async def close(self):
        if self._conn:
            await self._conn.close()
            logger.info("🔌 Jellyfin DB connection closed")

    async def query_one(self, sql: str, params: tuple = ()):
        rows = await self.query(sql, params)
        return rows[0] if rows else None

    async def query(self, sql: str, params: tuple = ()) -> list[aiosqlite.Row]:
        if not self._conn:
            await self.connect()
        logger.debug(f"📄 QUERY: {sql} | params: {params}")
        async with self._conn.execute(sql, params) as cursor:
            rows = await cursor.fetchall()
            return rows

    async def execute(self, sql: str, params: tuple = ()) -> int:
        if not self._conn:
            await self.connect()
        logger.debug(f"✏️ EXECUTE: {sql} | params: {params}")
        async with self._conn.execute(sql, params) as cursor:
            await self._conn.commit()
            return cursor.rowcount
    
    async def insert(self, sql: str, params: tuple = ()) -> int:
        """Execute an INSERT and return the new row ID (lastrowid)."""
        if not self._conn:
            await self.connect()
        logger.debug(f"➕ INSERT: {sql} | params: {params}")
        async with self._conn.execute(sql, params) as cursor:
            await self._conn.commit()
            return cursor.lastrowid

    async def execute_many(self, sql: str, param_list: list[tuple]) -> int:
        if not self._conn:
            await self.connect()
        logger.debug(f"📝 EXECUTE MANY: {sql} | {len(param_list)} items")
        await self._conn.executemany(sql, param_list)
        await self._conn.commit()
        return len(param_list)
