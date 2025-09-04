# core/bot/cogs/makemeworseplus/playlist_tracking_db_helpers.py
import json
from utils.logger_factory import setup_logger

logger = setup_logger(__name__)
TICKS_PER_SECOND = 10_000_000

async def find_candidate_playlists_by_first_item(vault_db, discord_id: str, first_item_id: str) -> list[dict]:
    sql = """
    SELECT up.id AS user_playlist_id, up.playlist_name, pi.item_id, pi.order_index
      FROM user_playlists up
      JOIN playlist_items pi ON pi.user_playlist_id = up.id
     WHERE up.discord_id = ?
       AND up.is_expired = 0
       AND pi.order_index IN (0,1)
     ORDER BY up.generated_at DESC
    """
    rows = await vault_db.query(sql, (str(discord_id),))
    
    # Group by playlist and check whether first track matches
    playlists = {}
    for r in rows:
        pid = r["user_playlist_id"]
        playlists.setdefault(pid, {})[r["order_index"]] = r["item_id"]
    
    # Keep those where index 0 matches
    out = []
    for pid, mapping in playlists.items():
        if mapping.get(0) == first_item_id:
            out.append({
                "user_playlist_id": pid, 
                "first": mapping.get(0), 
                "second": mapping.get(1)
            })
    return out

async def get_playlist_track_at_index(vault_db, user_playlist_id: int, idx: int) -> str | None:
    rows = await vault_db.query("""
        SELECT item_id FROM playlist_items 
        WHERE user_playlist_id = ? AND order_index = ? 
        LIMIT 1
    """, (int(user_playlist_id), int(idx)))
    return rows[0]["item_id"] if rows else None

async def upsert_playlist_session(vault_db, discord_id: str, user_playlist_id: int, 
                                  jf_playlist_id: str | None, current_index: int, 
                                  is_confirmed: bool) -> int:
    # Get existing
    rows = await vault_db.query("""
        SELECT id FROM playlist_sessions
         WHERE discord_id = ? AND user_playlist_id = ? AND is_complete = 0
         LIMIT 1
    """, (str(discord_id), int(user_playlist_id)))
    
    if rows:
        sid = rows[0]["id"]
        await vault_db.execute("""
            UPDATE playlist_sessions
               SET last_seen = CURRENT_TIMESTAMP,
                   current_index = ?,
                   is_confirmed = ?
             WHERE id = ?
        """, (int(current_index), int(bool(is_confirmed)), int(sid)))
        return sid
    
    # Insert new
    sid = await vault_db.insert("""
        INSERT INTO playlist_sessions (discord_id, user_playlist_id, jf_playlist_id, current_index, is_confirmed)
        VALUES (?, ?, ?, ?, ?)
    """, (str(discord_id), int(user_playlist_id), jf_playlist_id, int(current_index), int(bool(is_confirmed))))
    return sid

async def record_file_completion(vault_db, playlist_session_id: int, item_id: str, order_index: int, listen_duration: float = 0) -> int:
    return await vault_db.insert("""
        INSERT INTO playlist_file_events (playlist_session_id, item_id, order_index, listen_duration_seconds)
        VALUES (?, ?, ?, ?)
    """, (int(playlist_session_id), item_id, int(order_index), listen_duration))

async def mark_session_complete(vault_db, playlist_session_id: int) -> int:
    return await vault_db.execute("""
        UPDATE playlist_sessions 
        SET is_complete = 1, last_seen = CURRENT_TIMESTAMP
        WHERE id = ? AND is_complete = 0
    """, (int(playlist_session_id),))

async def get_track_runtime(vault_db, item_id: str) -> float:
    """Get individual track runtime in seconds"""
    rows = await vault_db.query("""
        SELECT metadata_json 
        FROM items 
        WHERE id = ?
    """, (item_id,))
    
    if rows and rows[0]["metadata_json"]:
        try:
            metadata = json.loads(rows[0]["metadata_json"])
            runtime_ticks = metadata.get("RunTimeTicks", 0)
            return runtime_ticks / TICKS_PER_SECOND
        except json.JSONDecodeError:
            logger.warning(f"Invalid JSON metadata for track {item_id}")
    
    return 300.0  # Default 5 minutes if no metadata

async def find_recent_incomplete_session_for_user(vault_db, discord_id: str, hours: int = 6):
    return await vault_db.query_one(  # <-- was query(...)
        """
        SELECT
            id                AS session_id,
            discord_id        AS discord_id,
            user_playlist_id  AS user_playlist_id,
            jf_playlist_id    AS jf_playlist_id,
            current_index     AS current_index,
            last_seen         AS last_seen,
            is_confirmed      AS is_confirmed,
            is_complete       AS is_complete
        FROM playlist_sessions
        WHERE discord_id = ?
          AND is_complete = 0
          AND last_seen >= DATETIME('now', ?)
        ORDER BY last_seen DESC
        LIMIT 1
        """,
        (str(discord_id), f'-{int(hours)} hours'),
    )

async def get_playlist_item_id_at_index(vault_db, user_playlist_id: int, index: int) -> str | None:
    """
    Returns the Jellyfin item_id for a given playlist and order_index.
    Always handles Row/tuple/scalar safely.
    """
    rows = await vault_db.query(
        """
        SELECT item_id
        FROM playlist_items
        WHERE user_playlist_id = ? AND order_index = ?
        LIMIT 1
        """,
        (int(user_playlist_id), int(index)),
    )
    return rows[0]["item_id"] if rows else None

async def get_order_index_for_item(vault_db, user_playlist_id: int, item_id: str) -> int | None:
    row = await vault_db.query_one(
        """
        SELECT order_index
        FROM playlist_items
        WHERE user_playlist_id = ? AND item_id = ?
        LIMIT 1
        """,
        (int(user_playlist_id), str(item_id)),
    )
    if not row:
        return None
    try:
        return int(row["order_index"])
    except Exception:
        try:
            return int(row[0])
        except Exception:
            return None


async def get_playlist_length(vault_db, user_playlist_id: int) -> int:
    """Get total number of tracks in a playlist"""
    rows = await vault_db.query("""
        SELECT COUNT(*) as track_count 
        FROM playlist_items 
        WHERE user_playlist_id = ?
    """, (int(user_playlist_id),))
    return rows[0]["track_count"] if rows else 0

async def get_playlist_info(vault_db, user_playlist_id: int) -> dict:
    """Get playlist metadata"""
    rows = await vault_db.query("""
        SELECT playlist_name, generated_at, num_files
        FROM user_playlists 
        WHERE id = ?
    """, (int(user_playlist_id),))
    
    if rows:
        return {
            "playlist_name": rows[0]["playlist_name"],
            "generated_at": rows[0]["generated_at"],
            "total_files": rows[0]["num_files"]
        }
    return {"playlist_name": "Unknown", "generated_at": None, "total_files": 0}

async def calculate_session_listen_time(vault_db, playlist_session_id: int) -> float:
    """Calculate total listening time for a session"""
    rows = await vault_db.query("""
        SELECT SUM(listen_duration_seconds) as total_time
        FROM playlist_file_events 
        WHERE playlist_session_id = ?
    """, (int(playlist_session_id),))
    return rows[0]["total_time"] if rows and rows[0]["total_time"] else 0.0

async def get_completed_playlist_count(vault_db, discord_id: str) -> int:
    """Get total number of playlists this user has completed"""
    rows = await vault_db.query("""
        SELECT COUNT(*) as completed_count
        FROM playlist_sessions 
        WHERE discord_id = ? AND is_complete = 1
    """, (str(discord_id),))
    
    return rows[0]["completed_count"] if rows else 0

async def get_item_title(vault_db, item_id: str) -> str | None:
    row = await vault_db.query_one(
        "SELECT title FROM items WHERE id = ? LIMIT 1",
        (str(item_id),),
    )
    if not row:
        return None
    try:
        return row["title"]
    except Exception:
        try:
            return row[0]
        except Exception:
            return None


