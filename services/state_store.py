import os
import logging
import asyncio
from pathlib import Path
from typing import TypeVar, Generic, Optional, List, Type
from pydantic import BaseModel
import config

logger = logging.getLogger(__name__)

T = TypeVar('T', bound=BaseModel)


class TypedStateStore(Generic[T]):
    def __init__(self, model_cls: Type[T], subdir: str):
        self.model_cls = model_cls
        self.subdir = subdir

    def _get_dir(self) -> Path:
        p = Path(config.STATE_DIR) / self.subdir
        p.mkdir(parents=True, exist_ok=True)
        return p

    def _get_filename(self, key: str) -> str:
        return f"{key}.json" if not key.endswith(".json") else key

    def get(self, key: str) -> Optional[T]:
        file_path = self._get_dir() / self._get_filename(key)
        if not file_path.exists():
            return None
        try:
            return self.model_cls.model_validate_json(file_path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.error(f"Failed to load state {key} from {self.subdir}: {e}")
            return None

    async def get_async(self, key: str) -> Optional[T]:
        return await asyncio.to_thread(self.get, key)

    def put(self, key: str, obj: T) -> None:
        file_path = self._get_dir() / self._get_filename(key)
        file_path.write_text(obj.model_dump_json(indent=2), encoding="utf-8")

    async def put_async(self, key: str, obj: T) -> None:
        await asyncio.to_thread(self.put, key, obj)

    def delete(self, key: str) -> None:
        file_path = self._get_dir() / self._get_filename(key)
        if file_path.exists():
            file_path.unlink()

    async def delete_async(self, key: str) -> None:
        await asyncio.to_thread(self.delete, key)

    def list_all(self) -> List[T]:
        items = []
        d = self._get_dir()
        if not d.exists():
            return items
        for file_path in d.glob("*.json"):
            if file_path.is_file():
                key = file_path.name[:-5]
                obj = self.get(key)
                if obj:
                    items.append(obj)
        return items

    async def list_all_async(self) -> List[T]:
        return await asyncio.to_thread(self.list_all)