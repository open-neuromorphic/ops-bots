import os
import signal
import subprocess
import logging

logger = logging.getLogger(__name__)


class ProcessSupervisor:
    @staticmethod
    def is_process_running(pid: int) -> bool:
        """Checks if a local PID is actively running."""
        if pid <= 0:
            return False
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False

    @staticmethod
    def is_systemd_available() -> bool:
        """Detects if systemd user services are available."""
        if os.name == "nt":
            return False
        try:
            subprocess.run(["systemctl", "--user", "is-system-running"], stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL)
            return True
        except FileNotFoundError:
            return False

    @staticmethod
    def get_systemd_service_status(service_name: str) -> bool:
        """Returns True if the systemd service is actively running."""
        if not ProcessSupervisor.is_systemd_available():
            return False
        res = subprocess.run(["systemctl", "--user", "is-active", service_name], capture_output=True, text=True)
        return res.stdout.strip() == "active"

    @staticmethod
    def restart_systemd_service(service_name: str):
        """Issues a restart command to a systemd user service."""
        subprocess.run(["systemctl", "--user", "restart", service_name])

    @staticmethod
    def stop_systemd_service(service_name: str):
        """Issues a stop command to a systemd user service."""
        subprocess.run(["systemctl", "--user", "stop", service_name])

    @classmethod
    def start_local_process(cls, cmd: list, pid_file: str, log_file: str = None, env: dict = None) -> int:
        """Starts a process locally, redirects output, and writes its PID to a file."""
        if log_file:
            os.makedirs(os.path.dirname(log_file) or ".", exist_ok=True)
            out = open(log_file, "a", encoding="utf-8")
            err = subprocess.STDOUT
        else:
            out = subprocess.DEVNULL
            err = subprocess.DEVNULL

        proc = subprocess.Popen(cmd, stdout=out, stderr=err, env=env)
        with open(pid_file, "w") as f:
            f.write(str(proc.pid))
        return proc.pid

    @classmethod
    def stop_local_process(cls, pid_file: str) -> bool:
        """Stops a process defined by a PID file and cleans up the file."""
        if not os.path.exists(pid_file):
            return False
        try:
            with open(pid_file, "r") as f:
                pid = int(f.read().strip())

            if cls.is_process_running(pid):
                if os.name == "nt":
                    subprocess.run(["taskkill", "/F", "/PID", str(pid)], stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL)
                else:
                    os.kill(pid, signal.SIGTERM)
            os.remove(pid_file)
            return True
        except (OSError, ValueError) as e:
            logger.debug(f"Failed to cleanly stop process from {pid_file}: {e}")
            try:
                os.remove(pid_file)
            except OSError:
                pass
            return False