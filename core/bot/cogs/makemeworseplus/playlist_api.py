# core/bot/cogs/makemeworseplus/playlist_api.py
import secrets, random
from urllib.parse import urlencode
from config.settings import settings
from utils.logger_factory import setup_logger
from utils.decorators import handle_exceptions
from utils.tag_metrics import increment_missing_tag
from .playlist_utils import extract_collection_category, is_priority_collection, is_mmw_name

logger = setup_logger(__name__)

def flatten_and_validate_tags(tags):
    """
    Safely flatten and validate tags, handling nested lists or mixed types
    """
    if not tags:
        return []
    
    flattened = []
    for item in tags:
        if isinstance(item, list):
            # Handle nested lists
            flattened.extend(flatten_and_validate_tags(item))
        elif isinstance(item, str) and item.strip():
            # Handle valid strings
            flattened.append(item.strip())
        # Ignore other types (None, empty strings, etc.)
    
    return flattened

@handle_exceptions
async def fetch_items_by_jellyfin_collection(jellyfin_client, name: str) -> list:
    logger.info(f"[fetch_items_by_jellyfin_collection] {name}")
    coll_query = urlencode({"IncludeItemTypes": "Collection", "Recursive": "true"})
    coll_response = await jellyfin_client.api.get(f"/Items?{coll_query}")
    match = next((c for c in coll_response.get("Items", []) if c["Name"].strip().lower() == name.strip().lower()), None)
    if not match:
        logger.warning(f"[fetch_items_by_jellyfin_collection] No match for {name}")
        return []
    child_query = urlencode({
        "ParentId": match["Id"],
        "IncludeItemTypes": "Audio",
        "Recursive": "true",
        "Fields": "Tags,Genres,BasicSyncInfo,Path"
    })
    child_response = await jellyfin_client.api.get(f"/Items?{child_query}")
    return child_response.get("Items", [])

@handle_exceptions
async def fetch_items_by_path_category(jellyfin_client, name: str) -> list:
    logger.info(f"[fetch_items_by_path_category] {name}")
    query = urlencode({
        "IncludeItemTypes": "Audio",
        "Recursive": "true",
        "Fields": "Tags,Genres,BasicSyncInfo,Path"
    })
    response = await jellyfin_client.api.get(f"/Items?{query}")
    all_items = response.get("Items", [])

    if name.startswith("Unethical Collection: "):
        target_cat = name.split(": ", 1)[1].strip().lower()
        return [
            item for item in all_items
            if (col := extract_collection_category(item.get("Path", "")))[0].strip().lower() == "sir's unethical collection"
            and col[1].strip().lower() == target_cat
        ]
    else:
        target_cat = name.strip().lower()
        return [
            item for item in all_items
            if extract_collection_category(item.get("Path", ""))[1].strip().lower() == target_cat
        ]

@handle_exceptions
def filter_by_tags(items, tags):
    """
    Filter items by tags, safely handling nested lists and mixed types
    """
    if not items:
        return []
    
    # Flatten tags safely at the start
    clean_tags = flatten_and_validate_tags(tags)
    if not clean_tags:
        return list(items)
    
    # Filter items that have at least one matching tag
    filtered = []
    clean_tags_lower = [tag.lower() for tag in clean_tags]
    
    for item in items:
        item_tags_lower = [t.lower() for t in item.get("Tags", [])]
        if any(tag in item_tags_lower for tag in clean_tags_lower):
            filtered.append(item)
    
    return filtered

@handle_exceptions
def _choose_guaranteed_items(pools: dict, used_ids: set) -> list:
    # Minimal: don't choose something already used
    guaranteed = []
    for name, pool in pools.items():
        pool_avail = [it for it in pool if it.get("Id") not in used_ids]
        if not pool_avail:
            logger.warning(f"[guaranteed] Skipping empty/used-out pool '{name}'")
            continue
        choice = random.choice(pool_avail)
        guaranteed.append(choice)
        used_ids.add(choice["Id"])
        coll, cat = extract_collection_category(choice.get("Path", ""))
        logger.info(f"[guaranteed] '{choice['Name']}' ({coll}/{cat}) from '{name}'")
    return guaranteed

@handle_exceptions
def _choose_items_round_robin(pools: dict, used_ids: set, needed: int) -> list:
    extra = []
    # Pre-filter each pool for items not yet used
    working = {name: [it for it in pool if it.get("Id") not in used_ids] for name, pool in pools.items()}
    # Drop empty pools up front
    working = {k: v for k, v in working.items() if v}
    if needed <= 0 or not working:
        if not working:
            logger.warning("[round_robin] All pools empty after filtering")
        return extra

    # Simple index pointer per pool (avoid generator truthiness traps)
    indices = {name: 0 for name in working}

    while needed > 0 and working:
        made_progress = False
        for name in list(working.keys()):
            pool = working[name]
            idx = indices[name]
            if idx >= len(pool):
                # pool exhausted; remove from rotation
                working.pop(name, None)
                indices.pop(name, None)
                continue

            item = pool[idx]
            indices[name] += 1  # advance pointer regardless

            iid = item.get("Id")
            if not iid or iid in used_ids:
                continue

            extra.append(item)
            used_ids.add(iid)
            needed -= 1
            made_progress = True

            coll, cat = extract_collection_category(item.get("Path", ""))
            logger.info(f"[round_robin] '{item['Name']}' ({coll}/{cat}) from '{name}'")

            if needed <= 0:
                break

        if not made_progress:
            # No new items added in a full sweep → stop
            break

    return extra

def _matches_any_tag_quick(item: dict, tags: list[str]) -> bool:
    """Check if item matches any of the given tags quickly"""
    if not tags:
        return False
    
    # Flatten tags safely
    clean_tags = flatten_and_validate_tags(tags)
    if not clean_tags:
        return False
    
    item_tags_lower = [t.lower() for t in item.get("Tags", [])]
    return any(tag.lower() in item_tags_lower for tag in clean_tags)

@handle_exceptions
async def _get_filler_items(
    jellyfin_client,
    count: int,
    used_ids: set,
    tags: list[str],
    *,
    ensure_curveball: bool = True,
    avoid_tags_entirely: bool = False,
) -> list:
    """
    Minimal change: still random-based, but now guarantees at least one curveball
    and (optionally) avoids tags entirely when requested.
    """
    if count <= 0:  # Guard against negative or zero count
        return []
    
    # Flatten tags at the start
    clean_tags = flatten_and_validate_tags(tags)
    
    query = urlencode({"IncludeItemTypes": "Audio", "Recursive": "true", "SortBy": "Random", "Fields": "Tags,BasicSyncInfo,Path"})
    response = await jellyfin_client.api.get(f"/Items?{query}")
    all_items = [it for it in response.get("Items", []) if it.get("Id") not in used_ids]
    
    if not all_items:  # No items available
        logger.warning("[filler] No items available for filler")
        return []
    
    # Partition by tag match using clean tags
    tagged = [it for it in all_items if _matches_any_tag_quick(it, clean_tags)]
    curve  = [it for it in all_items if not _matches_any_tag_quick(it, clean_tags)]
    
    filler = []

    # 1) Always try to add one curveball
    if ensure_curveball and curve:
        cb = random.choice(curve)
        filler.append(cb)
        used_ids.add(cb["Id"])
        coll, cat = extract_collection_category(cb.get("Path", ""))
        logger.info(f"[filler] curveball '{cb['Name']}' ({coll}/{cat})")
    
    # 2) Fill the rest:
    remaining_needed = max(0, count - len(filler))
    if remaining_needed <= 0:
        random.shuffle(filler)
        return filler[:count]

    if avoid_tags_entirely:
        pool = [it for it in curve if it["Id"] not in {x["Id"] for x in filler}]
    else:
        pool = tagged + [it for it in curve if it["Id"] not in {x["Id"] for x in filler}]

    if pool:
        add = random.sample(pool, min(remaining_needed, len(pool)))
        filler.extend(add)
        logger.info(f"[filler] Added {len(add)} {'non-tagged' if avoid_tags_entirely else 'tag-preferred'} items")

    random.shuffle(filler)
    return filler[:count]  # Ensure we don't exceed requested count

@handle_exceptions
async def generate_random_playlist(jellyfin_client, count: int, tags: list[str] | None = None) -> list:
    if count <= 0:  # Guard against invalid count
        logger.warning("[generate_random_playlist] Invalid count requested")
        return []
    
    # Flatten tags at the very start
    clean_tags = flatten_and_validate_tags(tags)
    logger.debug(f"[generate_random_playlist] Original tags: {repr(tags)}, Clean tags: {repr(clean_tags)}")
    
    used_ids = set()
    query = urlencode({"IncludeItemTypes": "Audio", "Recursive": "true", "SortBy": "Random", "Fields": "Tags,BasicSyncInfo,Path"})
    response = await jellyfin_client.api.get(f"/Items?{query}")
    all_items = [it for it in response.get("Items", []) if it.get("Id") not in used_ids]
    
    if not all_items:  # No items available at all
        logger.error("[generate_random_playlist] No audio items found in library")
        return []
    
    # Create tag pools only for valid tags
    tag_pools = {}
    for tag in clean_tags:
        pool = [it for it in all_items if tag.lower() in [t.lower() for t in it.get("Tags", [])]]
        if pool:  # Only add non-empty pools
            tag_pools[tag] = pool
        else:
            logger.warning(f"[generate_random_playlist] No items found for tag '{tag}'")
            try:
                await increment_missing_tag(tag)
            except Exception:
                logger.debug("[generate_random_playlist] increment_missing_tag failed (non-fatal)")    

    guaranteed = _choose_guaranteed_items(tag_pools, used_ids)
    target_extra = max(0, int(count * 0.75) - len(guaranteed))
    extra_tagged = _choose_items_round_robin(tag_pools, used_ids, target_extra)
    
    remaining_count = max(0, count - len(guaranteed) - len(extra_tagged))
    # Keep behavior here the same, but now we always guarantee a curveball.
    filler = await _get_filler_items(
        jellyfin_client, remaining_count, used_ids, clean_tags,
        ensure_curveball=True,
        avoid_tags_entirely=False
    )
    
    final_items = guaranteed + extra_tagged + filler
    random.shuffle(final_items)
    final_items = _reorder_long_items_last(final_items)
    logger.info(f"[generate_random_playlist] Assembled {len(final_items)} items (requested: {count})")
    return final_items

@handle_exceptions
async def generate_playlist(jellyfin_client, count: int, collections: list[str], tags: list[str] | None = None) -> list:
    if count <= 0:  # Guard against invalid count
        logger.warning("[generate_playlist] Invalid count requested")
        return []
    
    # Flatten tags at the start
    clean_tags = flatten_and_validate_tags(tags)
    logger.debug(f"[generate_playlist] Original tags: {repr(tags)}, Clean tags: {repr(clean_tags)}")
    
    if not collections:
        logger.warning("[generate_playlist] No collections provided — falling back to tags.")
        return await generate_random_playlist(jellyfin_client, count, clean_tags)

    # --- Minimal change: keep both preferred (tagged) and fallback (any) per collection
    preferred_by_collection, fallback_by_collection = {}, {}
    used_ids = set()
    
    for name in collections:
        items = await (fetch_items_by_jellyfin_collection(jellyfin_client, name) if is_priority_collection(name)
                       else fetch_items_by_path_category(jellyfin_client, name))
        if not items:
            logger.warning(f"[generate_playlist] No items for '{name}'")
            continue
        
        preferred = filter_by_tags(items, clean_tags) if clean_tags else list(items)
        fallback  = [it for it in items if it not in preferred]
        preferred_by_collection[name] = preferred
        fallback_by_collection[name]  = fallback

        if clean_tags:
            logger.info(f"[generate_playlist] {len(preferred)}/{len(items)} items after tag filtering in '{name}'")
        else:
            logger.info(f"[generate_playlist] {len(items)} items available in '{name}' (no tags provided)")

    if not preferred_by_collection:
        logger.warning("[generate_playlist] No collections loaded — falling back to random generation")
        return await generate_random_playlist(jellyfin_client, count, clean_tags)

    # --- Guaranteed: one per collection, prefer preferred, else fallback (round-robin start)
    guaranteed = []
    for coll in collections:
        chosen = None
        pool_pref = [it for it in preferred_by_collection.get(coll, []) if it.get("Id") not in used_ids]
        pool_fall = [it for it in fallback_by_collection.get(coll, []) if it.get("Id") not in used_ids]
        if pool_pref:
            chosen = random.choice(pool_pref)
        elif pool_fall:
            chosen = random.choice(pool_fall)

        if chosen:
            guaranteed.append(chosen)
            used_ids.add(chosen["Id"])
            ccol, ccat = extract_collection_category(chosen.get("Path", ""))
            logger.info(f"[guaranteed] '{chosen['Name']}' ({ccol}/{ccat}) from '{coll}'")
        else:
            logger.warning(f"[guaranteed] No available items for '{coll}' (both pools empty)")

    if not guaranteed:
        logger.warning("[generate_playlist] No guaranteed picks possible; falling back to random.")
        return await generate_random_playlist(jellyfin_client, count, clean_tags)
    
    # --- Extra: round-robin across preferred first, then fallback
    target_percentage = random.uniform(0.65, 0.75)
    target_extra = max(0, int(count * target_percentage) - len(guaranteed))

    # First pass: preferred items
    extra = _choose_items_round_robin(
        {k: [it for it in v if it.get("Id") not in used_ids] for k, v in preferred_by_collection.items()},
        used_ids,
        target_extra
    )

    # If still need more, take from fallback pools
    if len(extra) < target_extra:
        extra += _choose_items_round_robin(
            {k: [it for it in v if it.get("Id") not in used_ids] for k, v in fallback_by_collection.items()},
            used_ids,
            target_extra - len(extra)
        )
    
    remainder = max(0, count - len(guaranteed) - len(extra))

    # Determine if we've otherwise only used tag-matching items; if yes, make filler avoid tags
    only_used_tags = bool(clean_tags) and all(filter_by_tags([it], clean_tags) for it in (guaranteed + extra))

    filler = await _get_filler_items(
        jellyfin_client,
        remainder,
        used_ids,
        clean_tags,
        ensure_curveball=True,
        avoid_tags_entirely=only_used_tags
    )
    
    final_items = guaranteed + extra + filler
    random.shuffle(final_items)
    final_items = _reorder_long_items_last(final_items)
    
    logger.info(f"[generate_playlist] Final size {len(final_items)} (requested: {count})")
    return final_items

@handle_exceptions
def _reorder_long_items_last(items: list) -> list:
    if not items:  # Guard against empty list
        return items
    
    def mins(item):
        ticks = item.get("RunTimeTicks") or item.get("BasicSyncInfo", {}).get("RunTimeTicks", 0)
        return ticks / 10_000_000 / 60
    
    short = [i for i in items if mins(i) <= 120]
    long = [i for i in items if mins(i) > 120]
    logger.info(f"[reorder] {len(short)} short, {len(long)} long")
    return short + long

@handle_exceptions
async def create_playlist(
    jellyfin_client,
    user_id: str,
    items: list,
    name: str | None = None,
    name_prefix: str = "Make Me Worse+",
) -> tuple[str, str]:
    """
    Create a Jellyfin playlist and return (playlist_id, playlist_name).

    Normally, pass an explicit `name` (e.g., "<jf_username>'s Get Worse Playlist #n").
    If `name` is None, a fallback name is generated using `name_prefix` + random hex.
    """
    if not items:  # Guard against empty playlist creation
        raise ValueError("Cannot create playlist with no items")
    
    playlist_name = name or f"{name_prefix} ({secrets.token_hex(4)})"
    logger.info(f"[create_playlist] {playlist_name} with {len(items)} items")

    valid_items = [it for it in items if "Id" in it and it["Id"]]  # Filter out items without valid IDs
    if not valid_items:
        raise ValueError("No items with valid IDs found")

    payload = {
        "Name": playlist_name,
        "Ids": [it["Id"] for it in valid_items],
        "UserId": user_id,
        "IsPublic": False
    }
    playlist = await jellyfin_client.api.post("/Playlists", data=payload)
    if not playlist or not playlist.get("Id"):
        raise RuntimeError("No playlist ID returned")

    logger.info(f"[create_playlist] ID: {playlist['Id']}")
    return playlist["Id"], playlist_name

@handle_exceptions
def build_playlist_url(playlist_id: str) -> str:
    return f"{settings.JELLYFIN_URL}/web/#/details?id={playlist_id}&serverid={settings.JELLYFIN_SERVER_ID}"

@handle_exceptions
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