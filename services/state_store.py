import logging
from typing import TypeVar, Generic, Optional, List, Type
from pydantic import BaseModel
from services.cache import get as cache_get, put as cache_put, invalidate as cache_invalidate, list_keys

logger = logging.getLogger(__name__)

T = TypeVar('T', bound=BaseModel)

class TypedStateStore(Generic[T]):
    def __init__(self, model_cls: Type[T], subdir: str):
        self.model_cls = model_cls
        self.subdir = subdir

    def _get_filename(self, key: str) -> str:
        return f"{key}.json" if not key.endswith(".json") else key

    def get(self, key: str) -> Optional[T]:
        file_path = cache_get(self._get_filename(key), subdir=self.subdir)
        if not file_path:
            return None
        try:
            return self.model_cls.model_validate_json(file_path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.error(f"Failed to load state {key} from {self.subdir}: {e}")
            return None

    def put(self, key: str, obj: T) -> None:
        cache_put(self._get_filename(key), obj.model_dump_json(indent=2), subdir=self.subdir)

    def delete(self, key: str) -> None:
        cache_invalidate(self._get_filename(key), subdir=self.subdir)

    def list_all(self) -> List[T]:
        items = []
        for file_name in list_keys(subdir=self.subdir):
            if file_name.endswith(".json"):
                key = file_name[:-5]
                obj = self.get(key)
                if obj:
                    items.append(obj)
        return items