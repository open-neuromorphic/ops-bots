import os
import subprocess
import sys
import time


def is_systemd_available():
    if os.name == "nt":
        return False
    try:
        subprocess.run(["systemctl", "--user", "is-system-running"], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL)
        return True
    except FileNotFoundError:
        return False


def get_service_logs(lines=20):
    """Fetches the most recent journalctl logs for the bot service."""
    try:
        result = subprocess.run(
            ["journalctl", "--user", "-u", "onm-bot.service", "-n", str(lines), "--no-pager"],
            capture_output=True, text=True
        )
        return result.stdout.strip()
    except Exception as e:
        return f"Error fetching logs: {e}"


def main():
    if is_systemd_available():
        print("Restarting ONM Bot Service via systemd...")
        print(
            "Waiting for service to restart... (If this takes ~90s, the bot is failing to close gracefully and systemd is waiting to force-kill it)")

        start_time = time.time()
        subprocess.run(["systemctl", "--user", "restart", "onm-bot.service"])
        elapsed_time = time.time() - start_time

        print(f"\nRestart completed in {elapsed_time:.2f} seconds.")

        if elapsed_time > 10:
            print("\n⚠️ Restart took unusually long! This indicates the bot ignored the SIGTERM stop signal.")
            print("Systemd defaults to waiting 90 seconds before sending SIGKILL.")
            print("\n--- RECENT SYSTEMD LOGS (`journalctl --user -u onm-bot.service`) ---")
            print(get_service_logs(30))
            print("------------------------------------------------------------------")
            print("\n💡 Fix Options:")
            print("1. To forcefully speed this up in the future, edit your systemd service file:")
            print("   (e.g., ~/.config/systemd/user/onm-bot.service)")
            print("   Add 'TimeoutStopSec=5' under the [Service] block, then run 'systemctl --user daemon-reload'.")
            print(
                "2. Check the logs above for background tasks (like API calls) that might be preventing asyncio from closing cleanly.")
        else:
            print("Systemd restart signal processed quickly.")
            print("\n--- RECENT SYSTEMD LOGS ---")
            print(get_service_logs(10))

    else:
        print("Systemd not detected. Fallback to manual Tray PID termination...")
        TRAY_PID_FILE = ".tray.pid"
        if os.path.exists(TRAY_PID_FILE):
            try:
                with open(TRAY_PID_FILE, "r") as f:
                    pid = int(f.read().strip())
                if os.name == "nt":
                    subprocess.run(["taskkill", "/F", "/PID", str(pid)], stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL)
                else:
                    os.kill(pid, 15)
                os.remove(TRAY_PID_FILE)
                print(f"Terminated local tray process {pid}.")
            except OSError as e:
                print(f"Notice: Failed to terminate or clean up tray process PID {pid} (it may already be closed): {e}")

            env = os.environ.copy()
            env["PYTHONPATH"] = os.getcwd() + os.pathsep + env.get("PYTHONPATH", "")
            subprocess.Popen([sys.executable, "ops/tray_app.py"], env=env)
            print("Restarted tray application background thread.")


if __name__ == "__main__":
    main()