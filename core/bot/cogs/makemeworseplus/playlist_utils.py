# core/bot/cogs/makemeworseplus/playlist_utils.py
from pathlib import Path
from typing import List, Tuple
from urllib.parse import urlencode
from .playlist_deletion import delete_playlist
from utils.logger_factory import setup_logger

logger = setup_logger(__name__)

def extract_collection_category(path: str) -> tuple[str, str]:
    parts = Path(path).parts
    try:
        media_index = parts.index("media")
        collection = parts[media_index + 1] if len(parts) > media_index + 1 else "Unknown"
        category = parts[media_index + 2] if len(parts) > media_index + 2 else "Unknown"
        return collection, category
    except ValueError:
        return "Unknown", "Unknown"

def normalize_name(s: str) -> str:
    return (s or "").lower().replace(" ", "")

# 🔑 one canonical marker for all DB queries / detection
NAME_MARKER = "getworseplaylist#"

PRIORITY_COLLECTIONS = {
    "Sir's Core Hypnos",
    "Sir Dominic Store",
    "Subsys Files",
    "Locktober 2024",
    "Locktober 2025",
}

def is_priority_collection(name: str) -> bool:
    return name in PRIORITY_COLLECTIONS

def is_mmw_name(name: str) -> bool:
    return NAME_MARKER in normalize_name(name)

async def reconcile_deleted_playlists(vault_db, jellyfin_client, discord_id: str, jf_user_id: str) -> int:
    rows = await vault_db.query(
        f"""
        SELECT id, playlist_name
          FROM user_playlists
         WHERE discord_id = ?
           AND is_expired = 0
           AND REPLACE(LOWER(playlist_name), ' ', '') LIKE '%{NAME_MARKER}%'
        """,
        (str(discord_id),),
    )
    if not rows:
        return 0

    jf_names = await fetch_user_mmw_playlist_names(jellyfin_client, jf_user_id)
    jf_keys = {normalize_name(n) for n in jf_names}

    to_expire = [r["id"] for r in rows if normalize_name(r["playlist_name"]) not in jf_keys]
    if not to_expire:
        return 0

    qmarks = ",".join(["?"] * len(to_expire))
    count = await vault_db.execute(
        f"UPDATE user_playlists SET is_expired = 1 WHERE id IN ({qmarks})",
        tuple(to_expire),
    )
    logger.info(f"[reconcile_deleted_playlists] expired {count} rows for user {discord_id}")
    return count

async def expire_and_delete_old_playlists(vault_db, jellyfin_client) -> int:
    """
    Expire all user_playlists older than 48h (is_expired = 0) and attempt to
    delete their Jellyfin playlists.

    Returns:
        int: number of DB rows marked expired.
    """

    # 1) Collect candidates (DB is source of truth)
    rows = await vault_db.query("""
        SELECT up.id AS user_playlist_id,
               MIN(pi.jf_playlist_id) AS jf_playlist_id
          FROM user_playlists up
          LEFT JOIN playlist_items pi
                 ON pi.user_playlist_id = up.id
         WHERE up.is_expired = 0
           AND up.generated_at < DATETIME('now','-48 hours')
         GROUP BY up.id
    """)

    if not rows:
        return 0

    playlist_ids: List[int] = [r["user_playlist_id"] for r in rows]
    jf_ids: List[Tuple[int, str | None]] = [(r["user_playlist_id"], r["jf_playlist_id"]) for r in rows]

    # 2) Mark them expired in one UPDATE
    qmarks = ",".join(["?"] * len(playlist_ids))
    changed = await vault_db.execute(
        f"UPDATE user_playlists SET is_expired = 1 WHERE id IN ({qmarks})",
        tuple(playlist_ids),
    )

    # 3) Best-effort delete each corresponding Jellyfin playlist
    #    (Don't fail the whole operation if one delete errors.)
    for up_id, jf_pid in jf_ids:
        if not jf_pid:
            continue
        try:
            logger.info(f"[expire_and_delete_old_playlists] Deleting Jellyfin playlist {jf_pid} for user_playlist_id={up_id}")
            # Jellyfin DELETE usually returns empty body; treat as success if no exception.
            await delete_playlist(jellyfin_client, vault_db, jf_pid)
        except Exception as e:
            logger.warning(f"[expire_and_delete_old_playlists] Failed to delete Jellyfin playlist {jf_pid}: {e}")

    if changed:
        logger.info(f"[expire_and_delete_old_playlists] Expired {changed} playlists (48h+), delete attempted on Jellyfin.")
    return changed

async def fetch_user_mmw_playlist_names(jellyfin_client, jf_user_id: str) -> set[str]:
    q = urlencode({"IncludeItemTypes": "Playlist", "Recursive": "true", "UserId": jf_user_id, "Fields": "BasicSyncInfo"})
    resp = await jellyfin_client.api.get(f"/Items?{q}")
    items = resp.get("Items", []) if isinstance(resp, dict) else []
    names = set()
    for pl in items:
        name = pl.get("Name") or pl.get("NameSort") or ""
        if is_mmw_name(name):
            names.add(name)
    logger.info(f"[fetch_user_mmw_playlist_names] {len(names)} for {jf_user_id}")
    return names