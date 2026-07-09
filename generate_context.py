#!/usr/bin/env python3
import argparse
import os
import sys
from pathlib import Path
from datetime import datetime
import fnmatch

PROJECT_ROOT = Path(".").resolve()
sys.path.insert(0, str(PROJECT_ROOT))

# Import manifest for bot-specific scoping (Phase 3)
from core.manifest import BOTS, CORE_FILES

TMP_DIR = PROJECT_ROOT / "tmp"
FULL_OUTPUT_FILE = TMP_DIR / "discord-bot-code-dump.md"

EXCLUDED_DIRS = [
    ".git", ".idea", ".vscode", "__pycache__",
    ".venv", "venv", "tmp", "node_modules", "logs", "secrets"
]

EXCLUDED_FILES_PATTERNS = [
    ".DS_Store", "*.pyc", "*~", "discord-bot-code-dump.md", "package-lock.json",
    "credentials.json", "token*.json"
]

INCLUDE_PATTERNS = [
    "*.py", "*.pyi", "requirements.txt", "CLAUDE.md", "README.md", "*.j2", "*.json", "*.env.example"
]


def log(message):
    print(f"[CONTEXT GEN] {message}", file=sys.stderr)


def should_ignore(path: Path, root: Path) -> bool:
    relative_path_str = str(path.relative_to(root))
    if any(part in EXCLUDED_DIRS for part in Path(relative_path_str).parts):
        return True
    if any(fnmatch.fnmatch(path.name, pattern) for pattern in EXCLUDED_FILES_PATTERNS):
        return True
    return False


def should_include(filename: str) -> bool:
    return any(fnmatch.fnmatch(filename.lower(), pattern.lower()) for pattern in INCLUDE_PATTERNS)


def get_bot_allowed_paths(bot_name: str) -> list[str]:
    """Generates a list of valid files/directories based on the bot's manifest."""
    manifest = BOTS[bot_name]
    paths = ["README.md", "CLAUDE.md", ".env.example", manifest.entrypoint]

    # Map cog module names to file paths (e.g. cogs.context -> cogs/context.py)
    for cog in manifest.cogs:
        paths.append(cog.replace(".", "/") + ".py")

    paths.extend(manifest.dependencies)
    paths.extend(CORE_FILES)
    return paths


def is_path_in_bot_scope(file_path: Path, allowed_paths: list[str]) -> bool:
    """Checks if a file path falls under the allowed directories/files for the selected bot."""
    rel_path = file_path.relative_to(PROJECT_ROOT).as_posix()
    for allowed in allowed_paths:
        # Directory match
        if allowed.endswith('/') and rel_path.startswith(allowed):
            return True
        # Exact file match
        if rel_path == allowed:
            return True
    return False


def find_relevant_files(root: Path, scope_dir: str = None, bot_name: str = None) -> list[Path]:
    relevant_files = []
    scan_root = root / scope_dir if scope_dir else root
    if not scan_root.exists():
        log(f"Error: Target directory {scan_root} does not exist.")
        return []

    allowed_paths = get_bot_allowed_paths(bot_name) if bot_name else None

    if allowed_paths:
        log(f"Scoping context strictly to bot profile: '{bot_name}'")

    log(f"Scanning directory: {scan_root}")
    for current_dir_str, dir_names, file_names in os.walk(scan_root, topdown=True):
        current_path = Path(current_dir_str)
        dir_names[:] = [d for d in dir_names if d not in EXCLUDED_DIRS and not d.startswith('.')]

        for filename in file_names:
            file_path = current_path / filename
            if should_ignore(file_path, root):
                continue
            if should_include(filename):
                if allowed_paths and not is_path_in_bot_scope(file_path, allowed_paths):
                    continue
                relevant_files.append(file_path)

    relevant_files.sort()
    log(f"Found {len(relevant_files)} relevant project files.")
    return relevant_files


def get_markdown_lang(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    if ext in [".py", ".pyi"]:
        return "python"
    elif ext == ".env" or filename.startswith(".env"):
        return "env"
    elif ext in [".txt", ".md"]:
        return "markdown"
    elif ext == ".json":
        return "json"
    elif ext == ".j2":
        return "jinja"
    return ""


def should_skip_content(filename: str, content: str) -> bool:
    if filename in ["generate_context.py", "formatter.py", "test_extractors.py"]:
        return False
    lower_content = content.lower()
    patterns = ["client_secret", "refresh_token", "-----begin", "private_key"]
    return any(p in lower_content for p in patterns)


def generate_header(bot_name: str = None) -> str:
    scope_notice = f"**Scope:** Restricted to `{bot_name}` and core dependencies.\n" if bot_name else ""
    return f"""# Project Context (Full Checkpoint)

This file contains the content of key configuration, source code, and module files for the project. Image files are listed by path only. This serves as a full checkpoint.

**Project Root:** `{PROJECT_ROOT}`  
**Generated on:** `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}` 
{scope_notice}
### CRITICAL AI CODING REQUIREMENTS:
1. **Token Efficiency:** DO NOT use decorative comment blocks (e.g., `// ---------`). Keep comments dense.
2. **No File Headers:** Just provide the raw code inside the markdown fenced block. Provide filename before block.
3. **Commit Messages:** Provide commit message at end of response with **WHY** and **GOAL** of code changes
4. **Complete Files:** Always provide complete file content in responses — never truncated snippets or diff
5. If we are copying or moving files, provide the bash command to accomplish this
6. If there are follow up, todo, or testing steps needed, include these at the end of response.

---
"""


def generate_footer() -> str:
    return "\n--- END OF PROJECT CONTEXT ---"


def create_context_file(scope_dir: str = None, bot_name: str = None):
    log(f"Project Root: {PROJECT_ROOT}")

    output_filename = f"context-{bot_name}.md" if bot_name else "discord-bot-code-dump.md"
    target_output_file = TMP_DIR / output_filename

    try:
        TMP_DIR.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        log(f"Error: Could not create output directory {TMP_DIR}: {e}")
        sys.exit(1)

    files_to_process = find_relevant_files(PROJECT_ROOT, scope_dir, bot_name)

    readme_path = PROJECT_ROOT / "README.md"
    if readme_path in files_to_process:
        files_to_process.remove(readme_path)
        files_to_process.insert(0, readme_path)
    elif readme_path.exists() and not scope_dir:
        files_to_process.insert(0, readme_path)

    log(f"Generating context file: {target_output_file.relative_to(PROJECT_ROOT)}")
    header = generate_header(bot_name)
    footer = generate_footer()

    try:
        with open(target_output_file, "w", encoding="utf-8") as outfile:
            outfile.write(header + "\n")
            for file_path in files_to_process:
                relative_path = file_path.relative_to(PROJECT_ROOT)
                log(f"  Adding content of: {relative_path.as_posix()}")
                lang = get_markdown_lang(file_path.name)
                outfile.write(f"**{relative_path.as_posix()}**\n")

                try:
                    content = file_path.read_text(encoding="utf-8", errors="ignore")

                    if should_skip_content(file_path.name, content):
                        log(f"Warning: Skipped {relative_path} due to suspicious secret patterns.")
                        outfile.write(
                            f"> **SKIPPED `{relative_path.as_posix()}`: Suspicious secret patterns detected.**\n\n")
                        continue

                    if ".env" in file_path.name:
                        outfile.write("> **WARNING: Config file (POTENTIAL SECRETS - HANDLE WITH CARE)**\n")
                    outfile.write(f"```{lang}\n{content}")
                    if content and not content.endswith("\n"): outfile.write("\n")
                    outfile.write("```\n\n")
                except Exception as e:
                    log(f"Warning: Failed to read content from {relative_path}: {e}")
                    outfile.write(f"> **FAILED TO READ/DECODE `{relative_path.as_posix()}`**\n\n")
            outfile.write(footer + "\n")
    except IOError as e:
        log(f"Error: Could not write to output file {target_output_file}: {e}")
        sys.exit(1)

    file_size = target_output_file.stat().st_size
    log(f"Successfully generated context file: {target_output_file.relative_to(PROJECT_ROOT)} ({file_size} bytes)")


def main():
    parser = argparse.ArgumentParser(description="Generate a context file with project source code for AI analysis.")
    parser.add_argument("--dir", type=str, help="Specific directory to scope context generation", default=None)
    parser.add_argument("--bot", type=str, help="Scope context to a specific bot defined in core/manifest.py",
                        default=None)
    args = parser.parse_args()

    if args.bot and args.bot not in BOTS:
        log(f"Error: Bot '{args.bot}' not found in core.manifest.BOTS.")
        sys.exit(1)

    create_context_file(args.dir, args.bot)


if __name__ == "__main__":
    main()