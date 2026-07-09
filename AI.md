# AI Development Rules for Open Neuromorphic Bot

## Architecture & Separation of Concerns
- `cogs/`: Discord UI layer only. Parse options, defer interaction, delegate to `services/` or `pipeline/`, return formatted responses. NO heavy calculation, grouping, or data transformation inside cogs.
- `services/` & `pipeline/`: Pure business logic. Must remain 100% independent of `discord.py`.
- Dependency Injection: Pass `ContextLibrary()` instances to functions rather than instantiating `ContextLibrary()` locally.

## Security & Secrets
- All credentials/tokens must be written under `SECRETS_DIR`. Never construct a token/credential path elsewhere.

## Logging & Error Handling
- ALWAYS use `logger = logging.getLogger(__name__)`. Never use `print()` inside cogs, services, or pipelines (reserve `print()` only for CLI interactive scripts in `ops/` or root).
- NEVER use bare `except:` or `except Exception: pass`. Catch specific errors, or log unexpected errors with `logger.exception()`.
- In Discord cogs, route all unexpected exceptions to `await report_error(interaction, e, "Context message")`.

## Shared Utilities & State
- Disk Cache: Use `services.cache` (`get`, `put`, `is_stale` for content change, `is_expired` for time elapsed). Never create module-level in-memory dictionaries for caching.
- Discord Files: Use `utils.discord_utils.text_to_file(text, filename)` instead of repeating `io.BytesIO().encode('utf-8')`.
- Server Checks: Use `@require_clearance(operation, guild_only=True)` decorator instead of boilerplate `if not guild: return...` inside command handlers.
- LLM Routing: For interactive user-facing commands, use `route_with_retry(req)` instead of raw `route(req)` to handle transient API failures.

## Testing
- Changes to `services/` or `pipeline/` should come with a test.