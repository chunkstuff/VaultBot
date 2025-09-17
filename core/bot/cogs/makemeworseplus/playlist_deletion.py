# core/bot/cogs/makemeworseplus/playlist_deletion.py
from utils.logger_factory import setup_logger

logger = setup_logger(__name__)

async def playlist_exists(jellyfin_client, playlist_id: str) -> bool:
    """
    Check if a playlist exists on the Jellyfin server.
    Returns True if it exists, False if it doesn't exist (404) or on other errors.
    """
    try:
        logger.debug(f"[playlist_exists] Checking if playlist {playlist_id} exists")
        # Use query parameters to check for specific item
        resp = await jellyfin_client.api.get(f"/Items?Ids={playlist_id}")
        
        # Check if the response contains any items
        if isinstance(resp, dict) and "Items" in resp:
            exists = len(resp["Items"]) > 0
        else:
            exists = False
            
        logger.debug(f"[playlist_exists] Playlist {playlist_id} exists: {exists}")
        return exists
    except Exception as e:
        if "404" in str(e) or "Not Found" in str(e):
            logger.debug(f"[playlist_exists] Playlist {playlist_id} not found")
            return False
        # Other errors - log but assume it doesn't exist to be safe
        logger.warning(f"[playlist_exists] Error checking playlist {playlist_id}: {e}")
        return False

async def delete_playlist(jellyfin_client, vault_db, playlist_id: str) -> bool:
    """
    Deletes a Jellyfin playlist by ID.
    Returns True if deletion was successful (204, 200, or 404), False on other errors.
    """
    try:
        # First check if the playlist still exists
        if not await playlist_exists(jellyfin_client, playlist_id):
            logger.info(f"[delete_playlist] Playlist {playlist_id} doesn't exist - already deleted")
            await expire_playlist_by_jf_id(vault_db, playlist_id)
            return True
        
        # Use the correct path format for deletion
        logger.info(f"[delete_playlist] Attempting to delete Jellyfin playlist: {playlist_id}")
        resp = await jellyfin_client.api.delete(f"/Items/{playlist_id}")
        await expire_playlist_by_jf_id(vault_db, playlist_id)
        
        # Some Jellyfin servers return None for DELETE but still delete successfully
        if resp is None or isinstance(resp, dict) or resp == "":
            logger.info(f"[delete_playlist] Playlist {playlist_id} deleted successfully.")
            return True
        logger.warning(f"[delete_playlist] Unexpected response deleting {playlist_id}: {resp}")
        return True  # Still consider it successful
        
    except Exception as e:
        # Check if it's a 404 error (playlist already deleted)
        error_str = str(e)
        if "404" in error_str or "Not Found" in error_str:
            logger.info(f"[delete_playlist] Playlist {playlist_id} not found during deletion - already deleted")
            await expire_playlist_by_jf_id(vault_db, playlist_id)
            return True
        
        # Some other error occurred
        logger.error(f"[delete_playlist] Failed to delete playlist {playlist_id}: {e}")
        return False

async def expire_playlist(vault_db, user_playlist_id: int) -> int:
    """
    Mark a single playlist as expired in user_playlists.
    Returns number of rows updated (0 or 1).
    """
    sql = """
    UPDATE user_playlists
       SET is_expired = 1
     WHERE id = ? AND is_expired = 0
    """
    count = await vault_db.execute(sql, (int(user_playlist_id),))
    if count:
        logger.info(f"[expire_playlist] expired user_playlist_id={user_playlist_id}")
    return count

async def expire_playlist_by_jf_id(vault_db, jf_playlist_id: str) -> int:
    """
    Resolve user_playlist_id via playlist_items.jf_playlist_id, then expire it.
    Returns rows updated (0 or 1).
    """
    row = await vault_db.query_one(
        """
        SELECT DISTINCT user_playlist_id
          FROM playlist_items
         WHERE jf_playlist_id = ?
         LIMIT 1
        """,
        (str(jf_playlist_id),),
    )
    if not row:
        return 0

    # row is aiosqlite.Row (dict-like)
    user_playlist_id = int(row["user_playlist_id"])
    return await expire_playlist(vault_db, user_playlist_id)