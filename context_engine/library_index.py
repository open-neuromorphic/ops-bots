import os
import json
import logging
from models.library import LibraryEntry
import config

logger = logging.getLogger(__name__)


class ContextLibrary:
    _instance = None

    def __new__(cls, *args, **kwargs):
        """Implement Singleton pattern to ensure single source of truth in memory."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        # Prevent re-initialization if the instance already exists
        if self._initialized:
            return

        self.filepath = os.path.join(config.LIBRARY_BASE_DIR, "library.json")
        self.entries = {}
        self._load()
        self._initialized = True

    def _load(self):
        if os.path.exists(self.filepath):
            try:
                with open(self.filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for k, v in data.items():
                        try:
                            self.entries[k] = LibraryEntry(**v)
                        except Exception as e:
                            logger.warning(f"Dropped malformed library entry {k}: {e}")
            except Exception as e:
                logger.error(f"Error loading ContextLibrary: {e}")

    def _save(self):
        os.makedirs(os.path.dirname(self.filepath), exist_ok=True)
        with open(self.filepath, "w", encoding="utf-8") as f:
            json.dump({k: v.model_dump(exclude_none=True) for k, v in self.entries.items()}, f, indent=2)

    def get(self, entry_id: str) -> LibraryEntry | None:
        return self.entries.get(entry_id)

    def query(self, category_tags=None, source_type=None, since=None, max_tier=None):
        results = list(self.entries.values())
        if category_tags:
            results = [e for e in results if e.category_tag in category_tags]
        if source_type:
            results = [e for e in results if e.source_type == source_type]
        if since:
            results = [e for e in results if e.date >= since]
        if max_tier:
            tier_ranks = {"public": 0, "volunteer": 1, "ec": 2}
            max_rank = tier_ranks.get(max_tier, 2)
            results = [e for e in results if tier_ranks.get(e.audience_tier, 2) <= max_rank]
        return sorted(results, key=lambda x: x.date, reverse=True)

    def add_or_update(self, entry_id, **kwargs):
        if entry_id in self.entries:
            entry = self.entries[entry_id]
            for k, v in kwargs.items():
                if hasattr(entry, k):
                    setattr(entry, k, v)
            if 'excluded' in kwargs and not kwargs['excluded']:
                entry.exclusion_reason = None
        else:
            kwargs["id"] = entry_id
            if "title" not in kwargs: kwargs["title"] = "Untitled"
            if "date" not in kwargs: kwargs["date"] = "1970-01-01"
            if "source_type" not in kwargs: kwargs["source_type"] = "unknown"
            if "category_tag" not in kwargs: kwargs["category_tag"] = "uncategorized"
            self.entries[entry_id] = LibraryEntry(**kwargs)

        self._save()