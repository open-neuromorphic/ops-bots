---
document_type: "Functional Specification & Architecture Blueprint (v2.0)"
target_audience: "LLM Autonomous Developer / AI Coding Assistant"
project: "Open Neuromorphic Discord Bot & Context Engine (onm-bot)"
primary_language: "Python 3.x (discord.py, pydantic)"
core_framework: "utils/menu_framework.py (MenuSession, ScreenSpec)"
objective: "Implement interactive pipelines for Research, Content Ops, Scribe, and Identity, strictly adhering to condensed-list/detailed-view paradigms."
---

# LLM Implementation Specification

## 1. System Intent & User Stories
When implementing the following cogs, you must structure the UI/UX to satisfy these specific human workflows:

*   **Research Ops Workflow:** "As a moderator/user, I want to see a condensed list of active research discussions and new arXiv discoveries. I want to filter by state. I only want to see the massive abstract and the 'Submit' or 'Advance' buttons *after* I click into a specific paper's detail view, keeping the main list clean."
*   **Content Ops Workflow:** "As a volunteer, I need a frictionless 4-step pipeline: (1) Discover issues needing work, (2) See their current state, (3) Retrieve context/info to advance them, and (4) Execute the action (e.g., generate draft/approve). GitHub is too high-friction; this Discord UI must abstract it."
*   **Scribe Workflow:** "As an EC Admin, I need a dashboard to browse the AI's library index, review auto-generated summaries for accuracy before they are finalized, and build context bundles where I can see exactly what data is being fed to the LLM."
*   **Identity Workflow:** "As a moderator, I need a verifiable way to link a Discord user to a real-world identity/social media account via a challenge-response protocol before adding them to the entity glossary."

---

## 2. Research Pipeline (`cogs/menu_research.py`)

### 2.1 UI/UX Paradigm Shift
You must strictly enforce a **List -> Detail -> Action** flow. Do not render `paper.summary` in the `PAPER_LIST` screen. 

### 2.2 Menu Modes & States
**Mode A: Active Organization Pipeline (Default)**
*   **Source:** `onr_stats_store` joined with `onr_papers_store`
*   **Filters (Sub-menus):** Proposed, Active Discussion, Completed, Staged, Published.
*   **List Screen (`PAPER_LIST`):** 
    *   Row format: `{Title_Truncated}`
    *   Sub-text: `State: {Status} | 💬 {Comments} | 👥 {Participants} | ⏱️ {Time Remaining}`
    *   Buttons: `[Filter: State]`, `[View {ArXiv_ID}]` (Generates detail view).
*   **Detail Screen (`PAPER_DETAIL`):**
    *   Shows full Abstract, License, Authors.
    *   Shows Thread Link, live comment counts, and exact timer expirations.
    *   **Actions:** Depending on state, show `[Open Discussion]`, `[Close & Handoff]`, etc.

**Mode B: arXiv Discovery**
*   **Source:** `services/arxiv.py`
*   **List Screen:** Condensed title, author, date, and arXiv link ONLY.
*   **Detail Screen:** Shows Abstract. Action: `[Submit to QA Pipeline]`.

---

## 3. Content Ops Pipeline (`cogs/menu_content_ops.py`)

### 3.1 The 4-Step Pipeline UI
Refactor the menu to visually communicate the pipeline. The detail screen must act as a workstation for the issue.

### 3.2 State Resolution & Tagging
Use `pipeline/pr_automation.py` caches and GitHub API to derive the current state of an issue:
1.  **UNPROCESSED:** Issue is open, no draft in cache, no PR branch.
2.  **DRAFTED:** Draft JSON exists in local `pr_drafts` cache.
3.  **STAGED:** Branch `bot/issue-{num}` exists, PR is open.
4.  **PUBLISHED:** PR is merged/closed.

### 3.3 Detail Screen ("The Workstation")
When a user clicks an issue from the list, render:
*   **Step 1 (Context):** `[Generate Context Brief]` -> Hooks into `utils/retriever.py` to pull related library items for this issue.
*   **Step 2 (Draft):** `[Generate Draft]` -> Triggers LLM generation.
*   **Step 3 (Review):** `[View Staging]` -> URL to GitHub staging site.
*   **Step 4 (Publish):** `[Approve PR]` -> Pushes to production repo.
*   *Constraint:* Only show buttons relevant to the current derived state.

---

## 4. ONM-Scribe Dashboard (`cogs/menu_scribe.py`)

### 4.1 Architecture
Implement a 3-tab dashboard using `MenuSession.filter_mode` to switch views.

*   **Tab 1: Library Index Explorer**
    *   List all items in `library.json`.
    *   Buttons to add/edit `category_tag` arrays.
*   **Tab 2: Settings & Review Queue**
    *   Surface `artifacts/summaries/` and `meta/pending_review.json`.
    *   Allow EC admins to preview AI-generated summaries and click `[Approve]` or `[Reject & Regenerate]`.
*   **Tab 3: Context Sandbox**
    *   UI to select sources, build a context bundle, and test an LLM query.
    *   Must explicitly display: *"The following 4 files will be sent to the LLM..."* to ensure transparency.

---

## 5. Identity & Validation System (`cogs/onm_ident.py` & `models/meta.py`)

### 5.1 Schema Extensions
Update `EntityEntry` in `models/meta.py`:
```python
class VerificationStatus(str, Enum):
    UNVERIFIED = "unverified"
    PENDING_CHALLENGE = "pending_challenge"
    VERIFIED = "verified"

class EntityEntryExtended(BaseModel):
    # ... existing fields ...
    verification_status: VerificationStatus = VerificationStatus.UNVERIFIED
    verification_token: Optional[str] = None
    social_links: Dict[str, str] = Field(default_factory=dict)
```

### 5.2 Slash Commands & Workflow
Create a new cog `cogs/onm_ident.py` (Do NOT mix into research or scribe):
1.  `/onm-ident link <platform> <url>`: Bot generates a unique token (e.g., `ONM-VERIFY-8X2A`).
2.  Bot sets user state to `PENDING_CHALLENGE` and DMs instructions: *"Please post this token on your LinkedIn/GitHub bio temporarily, then click Verify."*
3.  `/onm-ident verify`: (Admin only for now) Admin manually checks the link, runs command, bot updates state to `VERIFIED` and writes to `entity_glossary.json`.

---

## 6. Execution Constraints for LLM Code Generation
When asked to implement parts of this specification, you MUST adhere to the following rules:

1.  **Iterative Generation:** Do not attempt to write all 4 pipelines in a single response. Await specific prompts (e.g., "Implement Phase 1: Research Menu Refactor").
2.  **No Hallucinated Imports:** Use ONLY the functions currently available in the provided project context. If a helper is missing (e.g., `get_live_thread_metrics`), you must explicitly write it inside the appropriate `pipeline/` file before importing it into the cog.
3.  **UI Framework:** All Discord interactions MUST use `ScreenSpec`, `ButtonSpec`, and `MenuSession` from `utils/menu_framework.py`. Do NOT instantiate `discord.ui.View` directly in the cogs.
4.  **Token Efficiency:** Return FULL file replacements for modified files. Do not use `// ... rest of file ...` truncation.