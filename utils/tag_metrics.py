# utils/tag_metrics.py
import json
import asyncio
from pathlib import Path

import aiofiles
import aiofiles.os as aos

from utils.logger_factory import setup_logger

logger = setup_logger(__name__)

DEFAULT_PATH = Path("logs") / "missing_tags.json"  # relative to CWD

# one lock per metrics file
_LOCKS: dict[str, asyncio.Lock] = {}

def _lock_for(path: Path) -> asyncio.Lock:
    key = str(path.resolve())
    if key not in _LOCKS:
        _LOCKS[key] = asyncio.Lock()
    return _LOCKS[key]

async def _ensure_dir(path: Path) -> None:
    try:
        # aiofiles.os.makedirs is async; parents=True via exist_ok handling
        await aos.makedirs(path.parent, exist_ok=True)
    except AttributeError:
        # fallback for older aiofiles: create top-level only (still non-blocking here)
        try:
            await aos.mkdir(path.parent)
        except FileExistsError:
            pass

async def _read_json(path: Path) -> dict:
    # No exists() check; just try to open and handle FileNotFoundError
    try:
        async with aiofiles.open(path, "r", encoding="utf-8") as f:
            text = await f.read()
        if not text.strip():
            return {}
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            logger.warning(f"[tag_metrics] invalid JSON in {path}; starting fresh")
            return {}
    except FileNotFoundError:
        return {}
    except Exception as e:
        logger.warning(f"[tag_metrics] read failed {path}: {e}; starting fresh")
        return {}

async def _atomic_write_json(path: Path, data: dict) -> None:
    tmp = path.with_suffix(".tmp")
    payload = json.dumps(data, indent=2, sort_keys=True)
    # write to temp
    async with aiofiles.open(tmp, "w", encoding="utf-8") as f:
        await f.write(payload)
    # rename temp -> final (atomic on same filesystem)
    try:
        await aos.replace(tmp, path)
    except Exception:
        # if replace unavailable/failed, try rename
        await aos.rename(tmp, path)

async def increment_missing_tag(tag: str, *, path: Path = DEFAULT_PATH) -> None:
    """
    Increment counter for a missing tag and persist to ./logs/missing_tags.json.
    Fully async: aiofiles + aiofiles.os. Case-insensitive keys.
    """
    tag = (tag or "").strip().lower()
    if not tag:
        return

    await _ensure_dir(path)
    lock = _lock_for(path)

    async with lock:
        logger.debug(f"[tag_metrics] lock acquired for {path}")
        data = await _read_json(path)
        data[tag] = int(data.get(tag, 0)) + 1
        try:
            await _atomic_write_json(path, data)
            logger.info(f"[tag_metrics] missing tag '{tag}' -> {data[tag]}")
        finally:
            logger.debug(f"[tag_metrics] lock released for {path}")

# optional helpers
async def read_missing_tag_counts(path: Path = DEFAULT_PATH) -> dict:
    await _ensure_dir(path)
    async with _lock_for(path):
        return await _read_json(path)

async def reset_missing_tag_counts(path: Path = DEFAULT_PATH) -> None:
    await _ensure_dir(path)
    async with _lock_for(path):
        await _atomic_write_json(path, {})
        logger.info(f"[tag_metrics] reset counts in {path}")
