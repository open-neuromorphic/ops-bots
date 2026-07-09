import os
import sys
import subprocess
import time
from datetime import datetime


def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')


def is_systemd_available():
    if os.name == "nt":
        return False
    try:
        subprocess.run(["systemctl", "--user", "is-system-running"], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL)
        return True
    except FileNotFoundError:
        return False


def launch_all_services():
    print("\nStarting Master Service Framework via restart.py...")
    subprocess.run([sys.executable, "ops/restart.py"])


def stop_all_services():
    print("\nStopping active services...")
    if is_systemd_available():
        subprocess.run(["systemctl", "--user", "stop", "onm-bot.service"])
    else:
        from restart import kill_process_by_file
        kill_process_by_file(".bot.pid")
        kill_process_by_file(".tray.pid")
    print("Services stopped successfully.")


def run_script(script_path: str, *args):
    print(f"\nExecuting {script_path}...")
    cmd = [sys.executable, script_path] + list(args)
    env = os.environ.copy()
    env["PYTHONPATH"] = os.getcwd() + os.pathsep + env.get("PYTHONPATH", "")
    subprocess.run(cmd, env=env)


def run_monthly_digest():
    print("======================================================")
    print("           MONTHLY EVENT DIGEST PIPELINE              ")
    print("======================================================")
    default_month = datetime.now().strftime("%Y-%m")
    source = input("Source Key [default: ec_transcript]: ").strip() or "ec_transcript"
    month = input(f"Month to Digest (YYYY-MM) [default: {default_month}]: ").strip() or default_month
    run_script("ops/run_monthly_digest.py", f"--source={source}", f"--month={month}")


MENU_OPTIONS = [
    ("Launch / Restart Master Service Framework", launch_all_services),
    ("Stop All Active Services", stop_all_services),
    ("Compile Bot Source Code Context Bundle for AI", lambda: run_script("generate_context.py")),
    ("Unified Sync of Local Sources to Library schema", lambda: run_script("ops/sync_sources.py")),
    ("Sync GitHub Snapshot Docs to Library", lambda: run_script("ops/sync_snapshot_docs.py")),
    ("Summarize Stale Transcripts (LLM Pipeline)", lambda: run_script("ops/summarize_transcripts.py")),
    ("Run Monthly Event Digest Pipeline", run_monthly_digest),
    ("Review AI Proposed Ledger Updates", lambda: run_script("ops/review_queue.py")),
    ("Build Global AI Context Guide (LLM Pipeline)", lambda: run_script("ops/build_guide.py")),
]


def display_menu():
    clear_screen()
    systemd_active = is_systemd_available()

    if systemd_active:
        res = subprocess.run(["systemctl", "--user", "is-active", "onm-bot.service"], capture_output=True, text=True)
        service_running = res.stdout.strip() == "active"
    else:
        service_running = os.path.exists(".tray.pid")

    bot_running = os.path.exists(".bot.pid")

    print("======================================================")
    print("            ONM SYSTEM CENTRAL CONTROL MENU           ")
    print("======================================================")
    print(f"  System Status:")
    print(f"    - Running Environment: [{'systemd --user' if systemd_active else 'Legacy PID Tracker'}]")
    print(f"    - Master Service Active: [{'YES' if service_running else 'NO'}]")
    print(f"    - Discord Bot Active:    [{'YES' if bot_running else 'NO'}]")
    print("------------------------------------------------------")
    for idx, (label, _) in enumerate(MENU_OPTIONS, 1):
        print(f"{idx:>3}. {label}")
    print("\n  0. Exit Control Panel")
    print("------------------------------------------------------")


def main():
    while True:
        display_menu()
        choice = input(f"Select an option (0-{len(MENU_OPTIONS)}): ").strip()

        if choice == "0":
            print("Exiting controller. Background services remain active if running.")
            sys.exit(0)

        if choice.isdigit() and 1 <= int(choice) <= len(MENU_OPTIONS):
            clear_screen()
            action_fn = MENU_OPTIONS[int(choice) - 1][1]
            action_fn()
            input("\nPress Enter to return to the main menu...")
        else:
            print("\nInvalid selection. Try again.")
            time.sleep(1.5)


if __name__ == "__main__":
    main()