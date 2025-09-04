# core/bot/cogs/vaultpulse/item_sync.py

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from asyncio import gather


class ItemSync:
    def __init__(self, client):
        self.client = client

    async def prepare_item_rows(self, buffer, sessions: list[dict[str, Any]] | None = None) -> list[tuple]:
        """
        Build upsert rows from buffer:
        (id, title, type, collection, category, last_fetched, metadata_json)
        """
        item_keys = buffer.get_item_ids()
        item_map = {}

        # Fetch active sessions if not passed in
        if sessions is None:
            sessions = await self.client.get_sessions()

        for session in sessions:
            item = session.get("NowPlayingItem")
            if item and item.get("Id") in item_keys:
                item_map[item["Id"]] = item

        # Fallback: fetch any missing items directly from Jellyfin API
        missing_item_ids = item_keys - item_map.keys()
        if missing_item_ids:
            fetched = await gather(*(self.client.api.fetch_item_detail(item_id) for item_id in missing_item_ids))
            for item in fetched:
                if item and item.get("Id"):
                    item_map[item["Id"]] = item
        
        now = datetime.utcnow().isoformat()
        rows = []

        for item_id in item_keys:
            item = item_map.get(item_id, {})
            title = item.get("Name", "Unknown Title")
            item_type = item.get("Type", "Unknown")
            path = item.get("Path", "")
            collection, category = self._extract_collection_category(path)

            rows.append((
                item_id,
                title,
                item_type,
                collection,
                category,
                now,
                json.dumps(item)
            ))

        return rows

    def _extract_collection_category(self, path: str) -> tuple[str, str]:
        parts = Path(path).parts
        try:
            media_index = parts.index("media")
            collection = parts[media_index + 1] if len(parts) > media_index + 1 else "Unknown"
            category = parts[media_index + 2] if len(parts) > media_index + 2 else "Unknown"
            return collection, category
        except ValueError:
            return "Unknown", "Unknown"
