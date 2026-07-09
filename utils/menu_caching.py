import json
import logging
from typing import Callable, Any, Coroutine
from pydantic import BaseModel
from services.cache import get as cache_get, put as cache_put, is_expired

logger = logging.getLogger(__name__)

async def fetch_with_cache(
        cache_key: str,
        fetch_coro: Callable[[], Coroutine[Any, Any, BaseModel]],
        model_cls: type[BaseModel],
        ttl_seconds: int = 600,
        force_refresh: bool = False
) -> BaseModel:
    """
    Standardized cache wrapper for paginated menu data to prevent API spam.
    Returns parsed Pydantic models.
    """
    cached_path = cache_get(f"{cache_key}.json", subdir="menu_data")

    if cached_path and not force_refresh and not is_expired(cached_path, ttl_seconds):
        try:
            return model_cls.model_validate_json(cached_path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning(f"Failed to parse cache {cache_key}, refreshing. Error: {e}")

    # Cache miss or expired
    data = await fetch_coro()
    cache_put(f"{cache_key}.json", data.model_dump_json(), subdir="menu_data")
    return data