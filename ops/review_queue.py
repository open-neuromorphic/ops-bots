#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import config
from models.meta import ThreadEntry, ThreadHistoryNote, load_threads_ledger

def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')

def load_queue() -> list[dict]:
    queue_path = Path(config.META_DIR) / "pending_review.json"
    if not queue_path.exists():
        return []
    try:
        return json.loads(queue_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"⚠️ Error parsing review queue JSON: {e}")
        return []
    except Exception as e:
        print(f"⚠️ Unexpected error loading review queue: {e}")
        return []

def save_queue(queue: list[dict]):
    queue_path = Path(config.META_DIR) / "pending_review.json"
    if not queue:
        if queue_path.exists():
            queue_path.unlink()
    else:
        queue_path.write_text(json.dumps(queue, indent=2), encoding="utf-8")

def process_queue():
    queue = load_queue()
    if not queue:
        print("🎉 No pending ledger updates to review!")
        return

    ledger_path = Path(config.META_DIR) / "threads_ledger.json"
    ledger = load_threads_ledger(ledger_path)

    while queue:
        item = queue[0]
        clear_screen()
        print("======================================================")
        print("            PENDING LEDGER UPDATE REVIEW              ")
        print("======================================================")
        print(f"Thread ID:    {item.get('thread_id')}")
        print(f"New Status:   {item.get('status')}")
        print(f"Update Date:  {item.get('date')}")
        print(f"Source Run:   {item.get('source_run')}")
        print("-" * 54)
        print(f"Proposed History Note:\n> {item.get('history_note')}")
        print("======================================================")

        if item.get('thread_id') not in ledger:
            print("⚠️ WARNING: This Thread ID does not exist in the ledger yet.")
            print("Accepting this will require you to manually fill in its title/summary later.\n")

        print("[A]ccept  |  [R]eject  |  [S]kip  |  [Q]uit")
        choice = input("> ").strip().lower()

        if choice == 'q':
            break
        elif choice == 's':
            queue.append(queue.pop(0))
        elif choice == 'r':
            queue.pop(0)
            print("❌ Rejected.")
        elif choice == 'a':
            tid = item.get('thread_id')
            if tid not in ledger:
                ledger[tid] = ThreadEntry(
                    title=f"New Thread: {tid}",
                    category="other",
                    status=item.get('status', 'active'),
                    summary="AI proposed thread. Needs human summary.",
                    last_updated=item.get('date', ''),
                    last_updated_by_run=item.get('source_run', '')
                )

            entry = ledger[tid]
            if item.get('status'): entry.status = item.get('status')
            if item.get('date'): entry.last_updated = item.get('date')
            if item.get('source_run'): entry.last_updated_by_run = item.get('source_run')

            entry.history.append(ThreadHistoryNote(
                date=item.get('date'),
                note=item.get('history_note'),
                source_entry=item.get('source_run')
            ))

            ledger_path.write_text(json.dumps({k: v.model_dump(exclude_none=True) for k, v in ledger.items()}, indent=2), encoding="utf-8")
            queue.pop(0)
            print("✅ Accepted & Applied to Ledger.")

    save_queue(queue)
    print("\nReview session complete. Returning to menu...")

if __name__ == "__main__":
    process_queue()