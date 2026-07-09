import aiohttp

_session = None

async def get_session() -> aiohttp.ClientSession:
    global _session
    if _session is None or _session.closed:
        _session = aiohttp.ClientSession()
    return _session

async def close_session():
    """Closes the global aiohttp session to prevent unclosed socket warnings on exit."""
    global _session
    if _session and not _session.closed:
        await _session.close()