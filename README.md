# Open Neuromorphic (ONM) Discord Bot Suite & Context Engine

> **🤖 Note to AI Assistants:** This document serves as the primary architectural mapping for the repository. When ingested via the context generator, use this document to understand module boundaries, data structures, and permission models before modifying code.

The Open Neuromorphic bot suite is a distributed system of specialized bots built on a shared context and pipeline framework. It serves three distinct organizational roles:

1. **Scribe (Knowledge & Reporting):** The AI Context Engine. A retrieval and summarization system that turns the org's raw operational history (meeting transcripts, Discord logs) into queryable context, governed by a human-in-the-loop review queue.
2. **Content Ops (GitHub & Events):** Project management, event calendar synchronization, and automated GitHub PR generation.
3. **Research (arXiv Pipeline):** The ONR (Open Neuromorphic Research) listener, which tracks, scores, and facilitates community peer-review of incoming open-source neuromorphic papers.

Because outputs from this system inform governance and public documentation, the "how it works" sections below describe the exact mechanisms. AI-generated conclusions never silently become organizational record.

---

## 🏛️ Codebase Architecture & Module Map

The repository strictly separates Discord UI, Data Pipelines, API wrappers, and data models:

- `cogs/` - **Discord UI Layer:** Discord slash commands, interactive UI views, and modals. Defers business logic to pipelines.
- `context_engine/` - **Data & Storage Layer:** Manages `library.json`, reads sources from disk, redacts secrets, and compiles Markdown bundles.
- `core/` - **Application Lifecycle:** Centralized `ONMBot` class and `manifest.py` (which defines the multi-bot routing and scopes).
- `models/` - **Pydantic Schemas:** Strong typing for the library, GitHub API, LLM requests, ONR tracking, and meta ledgers.
- `pipeline/` - **Heavy Processing:** Orchestrates ingest (GitHub, Discord, Fathom, arXiv), summarization (LLM digests), PR automation, and ONR state management.
- `services/` - **External APIs:** Wraps LLM routing (`llm.py` with local/cloud fallback), caching, GitHub API, and Google Calendar.
- `steps/` - **Google Workspace Subsystem:** Standalone tools for auditing Google Docs revisions, comments, and emails.
- `ops/` - **CLI Tooling:** Standalone maintenance, syncs, review queues, and the main system control panel (`main.py`).
- `utils/` - **Shared Helpers:** Role checks, template rendering, and interactive UI session management (`menu_framework.py`).

---

## 1. Using the Bot: Command Reference

The bot suite uses interactive UI dashboards and slash commands. Access is strictly governed by `config.OPERATION_ROLES`.

### 1.1 Interactive Dashboards (The Menu Paradigm)
The easiest way to interact with the bots is through their interactive UI panels, which provide paginated, context-aware controls:

| Command | Bot | What it does | Permission |
|---|---|---|---|
| `/onm-scribe` | Scribe | Opens the Context Engine dashboard. View index stats, request bundles, run the summarizer, or process the AI Ledger review queue. | `ec_admin` |
| `/onm-content-ops` | Content Ops | Opens the GitHub Projects module. Browse active issues, generate PR drafts, and push to staging/production interactively. | `volunteer_technical` |
| `/onm-research` | Research | Opens the ONR Explorer. Browse recent arXiv discoveries, monitor active community discussion threads, and review paper metrics. | `volunteer_technical` |

### 1.2 AI Context Engine & Scribe (`/onm-context`)

| Command | What it does | Permission |
|---|---|---|
| `/onm-context build` | Compiles a full Markdown context bundle (logs + transcripts + GitHub docs) and DMs it or saves it to disk. | `ec_admin` |
| `/onm-context digest <source> <month>` | Retrieves a **previously generated** monthly digest. | `ec_admin` |
| `/onm-context thread-status` | Looks up organizational threads from the AI-generated Threads Ledger. | `ec_admin` |
| `/onm-context who-is <name>` | Looks up a person in the Entity Glossary to reconcile transcriptions, Discord handles, and real names. | `ec_admin` |

### 1.3 Content Ops & PR Automation (`/onm-pr`, `/onm-project`)

| Command | What it does | Permission |
|---|---|---|
| `/onm-pr preview <issue>` | Asks the LLM to draft a Hugo content page from a GitHub issue, using repo archetypes as guardrails. Pushes to Staging. | `volunteer_technical` |
| `/onm-pr set-images` | Overrides the vision model's logo/image selection for a PR draft. | `volunteer_technical` |
| `/onm-pr approve <draft>` | Pushes the approved draft's branch to Staging and opens a cross-repo PR to Production. | `volunteer_technical` |
| `/onm-event-setup` | Creates synchronized Google Calendar and Discord scheduled events, providing Markdown copy-paste for Hugo. | `volunteer_technical` |

### 1.4 ONR Research Pipeline (`/onr`)

| Command | What it does | Permission |
|---|---|---|
| `/onr recent` | Scans and lists recent open-source arXiv papers matching ONM criteria. | All |
| `/onr submit <url>` | Manually submits an arXiv paper to the QA pipeline for community review. | All |
| `/onm-ident-link <platform> <url>` | Initiates secure linking of a Discord handle to a real identity/social profile for publication attribution. | All |
| `/onm-ident-verify` | Admin command to verify an identity linking challenge. | `ec_admin` |

### 1.5 Server Reporting

Scribe features commands like `/onm-top-contributors-report`, `/onm-role-analysis-report`, `/onm-channel-topics-report`, and `/onm-generate-activity-digest` to build text/CSV files of server state independent of the Context Engine.

---

## 2. How the Context Engine Works

Everything the bot can reason about must become a `LibraryEntry` in `library.json`. The engine processes:
1. **Sources:** Discord logs, meeting transcripts, GitHub docs.
2. **Summaries:** LLM-generated summaries to save token space.
3. **Ledgers:** AI-proposed organizational updates (`threads_ledger.json`).

**Verification Control:** When the monthly digest pipeline detects a change relevant to a strategic thread, it appends a proposal to `meta/pending_review.json`. A human must run the Review Queue (via `/onm-scribe` or CLI) to explicitly Accept or Reject the change. AI summarization *never* silently alters the institutional memory.

---

## 3. Local AI: llama.cpp Integration

The bot routes opportunistically. `services/llm.py` always attempts to hit the local `llama.cpp` server (default `http://127.0.0.1:8080`) first. 
- If the local server is running but times out, it falls back to the Gemini API.
- If the local server is offline, it instantly and silently falls back to the Gemini API.
- **Vision Exception:** Multimodal requests (e.g., PR image validation) are routed directly to Gemini, bypassing local text-only models.

See `ops/tray_app.py` for the exact `llama-server` invocation parameters used for staging.

---

## 4. Control Panel & Command-Line Tooling

`main.py` is the terminal control panel for system administration:

1. **Launch/Restart Master Service:** Restarts bots via `systemctl --user` or local PID tracking.
2. **Compile Context Bundle:** Dumps this repo's source code for AI analysis.
3. **Unified Sync:** Syncs live Discord data, GitHub docs, and transcripts to `library.json`.
4. **Run Monthly Digest / Summarizer:** Dispatches the LLM to process raw logs.
5. **Review AI Proposed Updates:** The human-in-the-loop CLI for ledger approval.

---

## 5. Environment Setup

Configuration is managed via `.env` (secrets) and `bot_config.json` (tuning). Key variables:

| Variable | Purpose |
|---|---|
| `DISCORD_TOKEN_SCRIBE`, `_CONTENT_OPS`, `_RESEARCH` | Individual bot tokens. Fallback is `DISCORD_BOT_TOKEN`. |
| `GEMINI_API_KEY` | Cloud LLM fallback authentication. |
| `GITHUB_TOKEN`, `GITHUB_TOKEN_BOT` | Read (docs) and Write (PR creation) GitHub permissions. |
| `EC_ADMIN_ROLE_IDS`, `VOLUNTEER_TECHNICAL_ROLE_IDS` | Comma-separated Discord Role IDs for clearance levels. |

---

## 6. Known Limitations & Caveats

- **Fathom Integration is stubbed:** `FathomApiClient` logic currently raises `NotImplementedError`. Transcripts must be supplied manually to the disk schema.
- **ONR arXiv Scraping Limits:** The arXiv pipeline respects a hard cap on polling to avoid `429 Too Many Requests`. Syncs run on a configured hourly interval.