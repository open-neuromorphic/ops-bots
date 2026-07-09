import os
import sys
import subprocess
import threading
import signal
import time
import tempfile
import shutil
from PIL import Image, ImageDraw

from ops.process_manager import ProcessSupervisor
from core.manifest import BOTS
import config

system_packages = '/usr/lib/python3/dist-packages'
if os.path.exists(system_packages) and system_packages not in sys.path:
    sys.path.append(system_packages)

import gi

gi.require_version("Gtk", "3.0")
try:
    gi.require_version("AyatanaAppIndicator3", "0.1")
    from gi.repository import AyatanaAppIndicator3 as AppIndicator3
except ValueError:
    gi.require_version("AppIndicator3", "0.1")
    from gi.repository import AppIndicator3
from gi.repository import Gtk, GLib

TRAY_PID_FILE = ".tray.pid"

LLAMA_SERVER_CMD = [
    os.path.expanduser(config.LLAMA_SERVER_BIN),
    "-m", os.path.expanduser(config.LLAMA_MODEL_PATH),
    "-ngl", "99",
    "-fa", "on",
    "--port", "8080",
    "-c", "120000",
    "-ctk", "q8_0",
    "-ctv", "q8_0",
    "--reasoning", "off"
]


class BotTrayApp:
    def __init__(self):
        self.llama_process = None
        self.icon_dir = os.path.join(tempfile.gettempdir(), "onm_bot_icons")

        os.makedirs("logs", exist_ok=True)

        self._write_tray_pid()
        self._setup_signals()
        self._generate_native_icons()

        self.indicator = AppIndicator3.Indicator.new(
            "onm_bot_tray",
            "bot_off_ai_off",
            AppIndicator3.IndicatorCategory.APPLICATION_STATUS
        )
        self.indicator.set_status(AppIndicator3.IndicatorStatus.ACTIVE)
        self.indicator.set_icon_theme_path(self.icon_dir)
        self.indicator.set_title("ONM Bot")

        self.bot_menu_items = {}
        self.menu = Gtk.Menu()
        self._build_menu()
        self.indicator.set_menu(self.menu)

        threading.Thread(target=self._monitor_processes, daemon=True).start()

    def _get_pid_file(self, bot_name: str) -> str:
        return f".{bot_name}.pid"

    def _write_tray_pid(self):
        with open(TRAY_PID_FILE, "w") as f:
            f.write(str(os.getpid()))

    def _setup_signals(self):
        signal.signal(signal.SIGINT, self.handle_exit_signal)
        signal.signal(signal.SIGTERM, self.handle_exit_signal)

    def handle_exit_signal(self, signum, frame):
        self._cleanup_and_exit()

    def _cleanup_and_exit(self):
        for bot_key in BOTS.keys():
            self.stop_bot(bot_key)
        self.stop_local_ai()

        if os.path.exists(TRAY_PID_FILE):
            try:
                os.remove(TRAY_PID_FILE)
            except OSError as e:
                print(f"Debug: Cleanup failed for {TRAY_PID_FILE}: {e}")
        Gtk.main_quit()
        os._exit(0)

    def _generate_native_icons(self):
        os.makedirs(self.icon_dir, exist_ok=True)

        def render(bot_on, ai_on, filename):
            size = 256
            image = Image.new("RGBA", (size, size), color=(0, 0, 0, 0))
            draw = ImageDraw.Draw(image)

            bot_color = (67, 160, 71, 255) if bot_on else (229, 57, 53, 255)
            draw.chord([32, 32, 224, 224], 90, 270, fill=bot_color)

            ai_color = (33, 150, 243, 255) if ai_on else (158, 158, 158, 255)
            draw.chord([32, 32, 224, 224], 270, 90, fill=ai_color)

            out_path = os.path.join(self.icon_dir, f"{filename}.png")
            image.resize((64, 64), Image.Resampling.LANCZOS).save(out_path)

        render(True, True, "bot_on_ai_on")
        render(True, False, "bot_on_ai_off")
        render(False, True, "bot_off_ai_on")
        render(False, False, "bot_off_ai_off")

    def open_log_terminal(self, log_file: str):
        log_path = os.path.abspath(log_file)
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        if not os.path.exists(log_path):
            open(log_path, 'a').close()

        if shutil.which("gnome-terminal"):
            subprocess.Popen(["gnome-terminal", "--", "tail", "-f", log_path])
        elif shutil.which("x-terminal-emulator"):
            subprocess.Popen(["x-terminal-emulator", "-e", f"tail -f {log_path}"])
        elif shutil.which("xterm"):
            subprocess.Popen(["xterm", "-e", f"tail -f {log_path}"])
        elif sys.platform == "darwin" and shutil.which("open"):
            subprocess.Popen(["open", "-a", "Terminal", log_path])
        else:
            print(f"Could not find a suitable terminal emulator to tail {log_path}")

    def _build_menu(self):
        # Dynamically build Bot menus from Manifest
        for bot_key, manifest in BOTS.items():
            bot_item = Gtk.MenuItem(label=manifest.name)
            bot_submenu = Gtk.Menu()
            bot_item.set_submenu(bot_submenu)

            status_item = Gtk.MenuItem(label="Status: Stopped")
            status_item.set_sensitive(False)
            bot_submenu.append(status_item)

            start_item = Gtk.MenuItem(label="Start")
            start_item.connect("activate", lambda _, name=bot_key: self.start_bot(name))
            bot_submenu.append(start_item)

            stop_item = Gtk.MenuItem(label="Stop")
            stop_item.connect("activate", lambda _, name=bot_key: self.stop_bot(name))
            bot_submenu.append(stop_item)

            restart_item = Gtk.MenuItem(label="Restart")
            restart_item.connect("activate", lambda _, name=bot_key: self.restart_bot(name))
            bot_submenu.append(restart_item)

            bot_submenu.append(Gtk.SeparatorMenuItem())

            log_item = Gtk.MenuItem(label="View Logs")
            log_item.connect("activate", lambda _, log=manifest.log_file: self.open_log_terminal(log))
            bot_submenu.append(log_item)

            self.menu.append(bot_item)

            self.bot_menu_items[bot_key] = {
                "status": status_item,
                "start": start_item,
                "stop": stop_item,
                "restart": restart_item
            }

        self.menu.append(Gtk.SeparatorMenuItem())

        # AI Menu
        ai_item = Gtk.MenuItem(label="Local AI Server")
        ai_submenu = Gtk.Menu()
        ai_item.set_submenu(ai_submenu)

        self.menu_ai_status = Gtk.MenuItem(label="Status: Offline")
        self.menu_ai_status.set_sensitive(False)
        ai_submenu.append(self.menu_ai_status)

        self.menu_ai_start = Gtk.MenuItem(label="Start")
        self.menu_ai_start.connect("activate", self.start_local_ai)
        ai_submenu.append(self.menu_ai_start)

        self.menu_ai_stop = Gtk.MenuItem(label="Stop")
        self.menu_ai_stop.connect("activate", self.stop_local_ai)
        ai_submenu.append(self.menu_ai_stop)

        ai_submenu.append(Gtk.SeparatorMenuItem())

        self.menu_ai_logs = Gtk.MenuItem(label="View Logs")
        self.menu_ai_logs.connect("activate", lambda _: self.open_log_terminal("logs/llama_server.log"))
        ai_submenu.append(self.menu_ai_logs)

        self.menu.append(ai_item)
        self.menu.append(Gtk.SeparatorMenuItem())

        item_restart = Gtk.MenuItem(label="Restart Master Service (systemd)")
        item_restart.connect("activate", self.restart_entire_service)
        self.menu.append(item_restart)

        item_quit = Gtk.MenuItem(label="Exit & Quit")
        item_quit.connect("activate", lambda *_: self._cleanup_and_exit())
        self.menu.append(item_quit)

        self.menu.show_all()

    def _monitor_processes(self):
        while True:
            bot_states = {key: self.is_bot_running(key) for key in BOTS.keys()}
            ai_running = self.is_ai_running()
            GLib.idle_add(self._update_ui_state, bot_states, ai_running)
            time.sleep(3)

    def _update_ui_state(self, bot_states: dict, ai_running: bool):
        any_bot_running = any(bot_states.values())
        icon_name = f"bot_{'on' if any_bot_running else 'off'}_ai_{'on' if ai_running else 'off'}"
        self.indicator.set_icon_full(icon_name, "ONM Bot")

        bot_str = "BOTS ON" if any_bot_running else "ALL OFF"
        ai_str = "AI" if ai_running else "OFF"
        self.indicator.set_label(f"{bot_str} | {ai_str}", "ONM Bot")

        for bot_key, is_running in bot_states.items():
            items = self.bot_menu_items.get(bot_key)
            if not items: continue

            items["status"].set_label(f"Status: {'Running' if is_running else 'Stopped'}")
            items["start"].set_sensitive(not is_running)
            items["stop"].set_sensitive(is_running)

        self.menu_ai_status.set_label(f"Status: {'Online' if ai_running else 'Offline'}")
        self.menu_ai_start.set_sensitive(not ai_running)
        self.menu_ai_stop.set_sensitive(ai_running)

        return False

    def start_bot(self, bot_name: str):
        if self.is_bot_running(bot_name): return
        manifest = BOTS.get(bot_name)
        if not manifest: return

        venv_python = os.path.join(os.getcwd(), ".venv", "bin", "python3")
        if not os.path.exists(venv_python): venv_python = sys.executable
        env = os.environ.copy()
        env["PYTHONPATH"] = os.getcwd() + os.pathsep + env.get("PYTHONPATH", "")

        ProcessSupervisor.start_local_process(
            cmd=[venv_python, manifest.entrypoint],
            pid_file=self._get_pid_file(bot_name),
            log_file=manifest.log_file,
            env=env
        )

        # Optimistic UI update
        bot_states = {key: self.is_bot_running(key) for key in BOTS.keys()}
        bot_states[bot_name] = True
        GLib.idle_add(self._update_ui_state, bot_states, self.is_ai_running())

    def stop_bot(self, bot_name: str):
        ProcessSupervisor.stop_local_process(self._get_pid_file(bot_name))

        bot_states = {key: self.is_bot_running(key) for key in BOTS.keys()}
        bot_states[bot_name] = False
        GLib.idle_add(self._update_ui_state, bot_states, self.is_ai_running())

    def restart_bot(self, bot_name: str):
        self.stop_bot(bot_name)
        time.sleep(1)
        self.start_bot(bot_name)

    def start_local_ai(self, *args):
        if self.is_ai_running(): return
        log_file = open(os.path.join("logs", "llama_server.log"), "a", encoding="utf-8")
        self.llama_process = subprocess.Popen(LLAMA_SERVER_CMD, stdout=log_file, stderr=subprocess.STDOUT)

        bot_states = {key: self.is_bot_running(key) for key in BOTS.keys()}
        GLib.idle_add(self._update_ui_state, bot_states, True)

    def stop_local_ai(self, *args):
        if self.llama_process:
            try:
                self.llama_process.terminate()
                self.llama_process.wait(timeout=5)
            except Exception as e:
                print(f"Debug: Graceful terminate failed, forcing kill: {e}")
                self.llama_process.kill()
            self.llama_process = None

        bot_states = {key: self.is_bot_running(key) for key in BOTS.keys()}
        GLib.idle_add(self._update_ui_state, bot_states, False)

    def restart_entire_service(self, *args):
        subprocess.Popen(["systemctl", "--user", "restart", "onm-bot.service"])

    def is_bot_running(self, bot_name: str) -> bool:
        pid_file = self._get_pid_file(bot_name)
        if os.path.exists(pid_file):
            try:
                with open(pid_file, "r") as f:
                    pid = int(f.read().strip())
                return ProcessSupervisor.is_process_running(pid)
            except OSError:
                pass
        return False

    def is_ai_running(self) -> bool:
        return self.llama_process is not None and self.llama_process.poll() is None

    def run(self):
        Gtk.main()


if __name__ == "__main__":
    if os.path.exists(TRAY_PID_FILE):
        try:
            with open(TRAY_PID_FILE, "r") as f:
                old_pid = int(f.read().strip())
            if ProcessSupervisor.is_process_running(old_pid):
                print(f"Tray app already running (PID: {old_pid}). Exiting.")
                sys.exit(0)
        except ValueError:
            pass

    app = BotTrayApp()
    app.run()