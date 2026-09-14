"""HTTP server and background job runner for the local web console."""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import traceback
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs

from .ui_state import JOB, JOB_LOCK, RUN_TIMEOUT_SECONDS
from .ui_templates import page_html


class LeadBotHandler(BaseHTTPRequestHandler):
    def _send_html(self, body: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(body.encode())

    def do_GET(self) -> None:
        if self.path == "/status":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            with JOB_LOCK:
                self.wfile.write(json.dumps(JOB).encode())
            return
        self._send_html(page_html())

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        data = parse_qs(self.rfile.read(length).decode())
        try:
            self._save_query(data)
            runner = self._find_python()
            threading.Thread(target=self._run_job, args=(runner,), daemon=True).start()
            self._send_html(page_html())
        except Exception as error:
            self._send_html(page_html().replace(
                'id="status-line">Ready',
                f'id="status-line">Could not start: {error}',
            ))

    @staticmethod
    def _save_query(data: dict[str, list[str]]) -> None:
        config_path = Path("config.json")
        base_config = json.loads(config_path.read_text(encoding="utf-8")) if config_path.exists() else {}
        base_config["queries"] = [{
            "country": data["country"][0],
            "region": data["region"][0],
            "niche": data["niche"][0],
        }]
        config_path.write_text(json.dumps(base_config, indent=2), encoding="utf-8")

    @staticmethod
    def _find_python() -> str:
        venv_python = Path(".venv/Scripts/python.exe")
        if not venv_python.exists():
            venv_python = Path(".venv/bin/python")
        return str(venv_python) if venv_python.exists() else sys.executable

    @staticmethod
    def _run_job(runner: str) -> None:
        with JOB_LOCK:
            JOB.update(
                status="running",
                progress=0,
                message="Starting...",
                log=[f"Using interpreter: {runner}", f"Working dir: {Path.cwd()}"],
            )
        try:
            process = subprocess.Popen(
                [runner, "-m", "leadbot.main", "--config", "config.json"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                cwd=str(Path.cwd()),
            )
            timer = threading.Timer(RUN_TIMEOUT_SECONDS, process.kill)
            timer.start()
            try:
                LeadBotHandler._read_process_output(process)
                returncode = process.wait()
            finally:
                timer.cancel()

            with JOB_LOCK:
                if returncode == 0:
                    JOB["status"] = "complete"
                    JOB["progress"] = 100
                else:
                    JOB["status"] = "error"
                    JOB["message"] = JOB["message"] or f"Failed (exit code {returncode})"
        except Exception as error:
            with JOB_LOCK:
                JOB["status"] = "error"
                JOB["message"] = f"Could not run collection: {error}"
                JOB["log"].append(traceback.format_exc())

    @staticmethod
    def _read_process_output(process: subprocess.Popen) -> None:
        if process.stdout is None:
            return
        for raw_line in process.stdout:
            line = raw_line.rstrip("\n")
            if not line:
                continue
            with JOB_LOCK:
                if line.startswith("PROGRESS "):
                    parts = line.split(" ", 2)
                    try:
                        JOB["progress"] = max(0, min(100, int(parts[1])))
                        JOB["message"] = parts[2] if len(parts) > 2 else ""
                    except (IndexError, ValueError):
                        pass
                JOB["log"].append(line)
                JOB["log"] = JOB["log"][-40:]


def run_server(host: str = "127.0.0.1", port: int = 8080) -> None:
    print(f"LeadBot UI: http://{host}:{port}")
    HTTPServer((host, port), LeadBotHandler).serve_forever()
