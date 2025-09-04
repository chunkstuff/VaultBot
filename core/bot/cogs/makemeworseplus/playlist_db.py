# core/bot/cogs/makemeworseplus/playlist_db.py
import json
from utils.logger_factory import setup_logger
from .playlist_utils import normalize_name, NAME_MARKER, is_mmw_name
from .playlist_api import fetch_user_mmw_playlist_names

logger = setup_logger(__name__)

async def log_playlist_creation(vault_db, discord_id: str, playlist_name: str, items: list,
                                collections: list[str] | None = None, tags: list[str] | None = None) -> int:
    collections = collections or []
    tags = tags or []
    item_ids = [it["Id"] for it in items if "Id" in it]
    sql = """
    INSERT INTO user_playlists (
        discord_id, playlist_name, playlist_items,
        num_files, collections, tags, is_expired
    ) VALUES (?, ?, ?, ?, ?, ?, 0)
    """
    params = (str(discord_id), playlist_name, json.dumps(item_ids), len(item_ids),
              json.dumps(collections), json.dumps(tags))
    playlist_id = await vault_db.insert(sql, params)
    logger.info(f"[log_playlist_creation] id={playlist_id} user={discord_id} name='{playlist_name}' files={len(item_ids)}")
    return playlist_id

async def expire_old_playlists(vault_db) -> int:
    sql = """
    UPDATE user_playlists
       SET is_expired = 1
     WHERE is_expired = 0
       AND generated_at < DATETIME('now', '-48 hours')
    """
    count = await vault_db.execute(sql)
    if count: logger.info(f"[expire_old_playlists] expired {count}")
    return count




async def count_active_playlists(vault_db, discord_id: str) -> int:
    rows = await vault_db.query(
        "SELECT COUNT(*) AS total FROM user_playlists WHERE discord_id = ? AND is_expired = 0",
        (str(discord_id),),
    )
    return rows[0]["total"] if rows else 0


def _mmw_name_key(name: str) -> str:
    return (name or "").lower().replace(" ", "")

async def get_next_playlist_number(vault_db, discord_id: str) -> int:
    rows = await vault_db.query(
        f"""
        SELECT COUNT(*) AS total
          FROM user_playlists
         WHERE discord_id = ?
           AND REPLACE(LOWER(playlist_name), ' ', '') LIKE '%{NAME_MARKER}%'
        """,
        (str(discord_id),),
    )
    total = rows[0]["total"] if rows else 0
    return total + 1

def build_sequential_name(username: str, n: int) -> str:
    return f"{username}'s Get Worse Playlist #{n}"

async def log_playlist_items(vault_db, user_playlist_id: int, jf_playlist_id: str | None, items: list) -> int:
    """
    Bulk insert playlist item rows with order_index.
    """
    sql = """
    INSERT INTO playlist_items (user_playlist_id, jf_playlist_id, item_id, order_index)
    VALUES (?, ?, ?, ?)
    """
    params = [
        (user_playlist_id, jf_playlist_id, it["Id"], idx)
        for idx, it in enumerate(items)
        if "Id" in it
    ]
    if not params:
        return 0
    count = await vault_db.execute_many(sql, params)
    logger.info(f"[log_playlist_items] inserted {count} rows for user_playlist_id={user_playlist_id}")
    return count
