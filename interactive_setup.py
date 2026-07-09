#!/usr/bin/env python3
import os
import sys
import time
import subprocess
from typing import Callable, Dict

def clear_screen() -> None:
    os.system('cls' if os.name == 'nt' else 'clear')

def run_command(command_list):
    script_name = os.path.basename(command_list[-1])
    print(f"\n--- Running: {' '.join(command_list)} ---")
    print("--- (You should see output from the script below) ---")

    env = os.environ.copy()
    project_root = os.getcwd()
    env["PYTHONPATH"] = project_root + os.pathsep + env.get("PYTHONPATH", "")

    try:
        subprocess.run(
            [sys.executable] + command_list[1:],
            check=True,
            text=True,
            env=env
        )
        print(f"--- Finished: {script_name} ---\n")
        return True
    except subprocess.CalledProcessError as e:
        print(f"\n!!! ERROR executing {script_name} !!!")
        print(f"Return Code: {e.returncode}")
        return False
    except FileNotFoundError:
        print(f"!!! ERROR: Could not find script {script_name}. Make sure it exists. !!!")
        return False

def setup_google_calendar_api():
    print("This will trigger the Google authentication flow for the Calendar API.")
    print("A browser window should open. Please log in and grant permissions.")
    print("This will create 'secrets/token_calendar.json' upon success.")
    input("Press Enter to continue...")
    run_command(["python", "ops/auth_calendar.py"])

def display_menu() -> None:
    clear_screen()
    calendar_token_exists = os.path.exists(os.path.join('secrets', 'token_calendar.json'))

    print("======================================================")
    print("           INTERACTIVE SETUP & AUTH TOOL            ")
    print("======================================================")
    print("\nThis script helps you authenticate with Google APIs.")
    print("Run these steps once to generate token files in your secrets/ directory.")
    print("------------------------------------------------------")
    print(f"  1. Authenticate with Google Calendar API    (Status: {'CONFIGURED' if calendar_token_exists else 'NOT CONFIGURED'})")
    print("\n  0. Exit")
    print("------------------------------------------------------")

def main() -> None:
    task_map: Dict[str, Callable[[], None]] = {
        '1': setup_google_calendar_api,
    }

    while True:
        display_menu()
        choice = input("Enter your choice (0-1): ")

        if choice == '0':
            print("Exiting.")
            sys.exit(0)
        task_function = task_map.get(choice)

        if task_function:
            clear_screen()
            try:
                task_function()
            except Exception as e:
                print(f"\n--- AN ERROR OCCURRED ---")
                print(f"Error during execution: {e}")
            print("\n---------------------------------")
            input("Task finished. Press Enter to return to the menu...")
        else:
            print("\nInvalid choice. Please try again.")
            time.sleep(2)

if __name__ == "__main__":
    main()