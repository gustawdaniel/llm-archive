#!/usr/bin/env python3
"""
Local Diagnostic Logger Server for Brain LLM Sync Extensions.
Listens on http://127.0.0.1:3040.
Accepts logs from browser extensions, prints colorized console output,
and writes structured JSONL records to extension/logs/sync.log.
"""

import json
import os
import sys
import threading
import urllib.request
import urllib.error
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from pathlib import Path

PORT = 3040
REMOTE_API = os.getenv("LLM_API_URL", "http://localhost:8080")
LOGS_DIR = Path(__file__).parent / "logs"
LOG_FILE = LOGS_DIR / "sync.log"

MAX_MEMORY_LOGS = 1000
memory_logs = []
logs_lock = threading.Lock()

# Terminal colors
COLOR_RESET = "\033[0m"
COLOR_RED = "\033[31m"
COLOR_GREEN = "\033[32m"
COLOR_YELLOW = "\033[33m"
COLOR_BLUE = "\033[34m"
COLOR_MAGENTA = "\033[35m"
COLOR_CYAN = "\033[36m"
COLOR_GRAY = "\033[90m"


class DiagnosticHandler(BaseHTTPRequestHandler):
    def _set_cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def do_OPTIONS(self):
        self.send_response(204)
        self._set_cors_headers()
        self.end_headers()

    def do_POST(self):
        if self.path == "/log":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode("utf-8") if content_length > 0 else "{}"
            try:
                data = json.loads(body)
                now_str = datetime.now().strftime("%H:%M:%S")
                level = data.get("level", "info").lower()
                source = data.get("source", "extension")
                message = data.get("message", "")
                details = data.get("details", None)
                iso_ts = data.get("timestamp", datetime.now(timezone.utc).isoformat())

                record = {
                    "timestamp": iso_ts,
                    "level": level,
                    "source": source,
                    "message": message,
                    "details": details
                }

                # Memory buffer & file append (thread-safe)
                with logs_lock:
                    memory_logs.append(record)
                    if len(memory_logs) > MAX_MEMORY_LOGS:
                        memory_logs.pop(0)

                    # Append to file
                    LOGS_DIR.mkdir(parents=True, exist_ok=True)
                    with open(LOG_FILE, "a", encoding="utf-8") as f:
                        f.write(json.dumps(record, ensure_ascii=False) + "\n")

                # Console format
                color = {
                    "error": COLOR_RED,
                    "warn": COLOR_YELLOW,
                    "warning": COLOR_YELLOW,
                    "success": COLOR_GREEN,
                    "info": COLOR_CYAN,
                    "debug": COLOR_GRAY
                }.get(level, COLOR_CYAN)

                detail_str = ""
                if details:
                    detail_str = f" {COLOR_GRAY}{json.dumps(details, ensure_ascii=False)[:300]}{COLOR_RESET}"

                print(f"{COLOR_GRAY}[{now_str}]{COLOR_RESET} {color}[{level.upper()}]{COLOR_RESET} {COLOR_MAGENTA}[{source}]{COLOR_RESET} {message}{detail_str}", flush=True)

                self.send_response(200)
                self._set_cors_headers()
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"status":"ok"}')
            except Exception as e:
                self.send_response(400)
                self._set_cors_headers()
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))
            return

        if self.path in ("/ingest", "/api/v1/ingest"):
            try:
                length = int(self.headers.get("content-length", 0))
                raw_body = self.rfile.read(length)
                target_url = f"{REMOTE_API}/api/v1/ingest"
                req = urllib.request.Request(
                    target_url,
                    data=raw_body,
                    headers={"Content-Type": "application/json"},
                    method="POST"
                )
                with urllib.request.urlopen(req, timeout=30) as resp:
                    resp_data = resp.read()
                    self.send_response(resp.status)
                    self._set_cors_headers()
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(resp_data)
                    print(f"{COLOR_GREEN}[Bridge Proxy] Successfully forwarded ingest to {target_url}{COLOR_RESET}", flush=True)
            except urllib.error.HTTPError as e:
                err_data = e.read()
                self.send_response(e.code)
                self._set_cors_headers()
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(err_data)
                print(f"{COLOR_RED}[Bridge Proxy] Backend returned HTTP {e.code}{COLOR_RESET}", flush=True)
            except Exception as e:
                self.send_response(502)
                self._set_cors_headers()
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": f"Bridge error: {str(e)}"}).encode("utf-8"))
                print(f"{COLOR_RED}[Bridge Proxy] Bridge forwarding error: {e}{COLOR_RESET}", flush=True)
            return

        if self.path == "/clear":
            with logs_lock:
                memory_logs.clear()
                if LOG_FILE.exists():
                    LOG_FILE.write_text("", encoding="utf-8")
            self.send_response(200)
            self._set_cors_headers()
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status":"cleared"}')
            print(f"{COLOR_YELLOW}[Diagnostic Server] Logs buffer and file cleared.{COLOR_RESET}", flush=True)
            return

        self.send_response(404)
        self.end_headers()

    def do_GET(self):
        if self.path.startswith("/sync/status") or self.path.startswith("/api/v1/sync/status"):
            try:
                query = self.path[self.path.find("?"):] if "?" in self.path else ""
                target_url = f"{REMOTE_API}/api/v1/sync/status{query}"
                req = urllib.request.Request(target_url, headers={"Accept": "application/json"})
                with urllib.request.urlopen(req, timeout=15) as resp:
                    resp_data = resp.read()
                    self.send_response(resp.status)
                    self._set_cors_headers()
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(resp_data)
            except Exception as e:
                self.send_response(502)
                self._set_cors_headers()
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": f"Bridge error: {str(e)}"}).encode("utf-8"))
            return

        if self.path == "/logs":
            with logs_lock:
                logs_snapshot = list(memory_logs)
            self.send_response(200)
            self._set_cors_headers()
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(logs_snapshot, indent=2, ensure_ascii=False).encode("utf-8"))
            return

        if self.path in ("/device", "/config", "/info"):
            import socket
            hostname = socket.gethostname() or os.uname().nodename
            self.send_response(200)
            self._set_cors_headers()
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({
                "device": hostname,
                "hostname": hostname,
                "os": sys.platform
            }).encode("utf-8"))
            return

        if self.path == "/health" or self.path == "/":
            self.send_response(200)
            self._set_cors_headers()
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({
                "status": "running",
                "port": PORT,
                "buffered_logs": len(memory_logs),
                "log_file": str(LOG_FILE)
            }).encode("utf-8"))
            return

        self.send_response(404)
        self.end_headers()

    def log_message(self, format, *args):
        # Suppress standard HTTP request log to keep console focused on extension telemetry
        pass


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    """Multi-threaded HTTP server to prevent slow upstream requests from blocking local telemetry/health."""
    daemon_threads = True
    allow_reuse_address = True


def run():
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    server_address = ("127.0.0.1", PORT)
    httpd = ThreadedHTTPServer(server_address, DiagnosticHandler)
    print(f"\n{COLOR_GREEN}=== Brain Extension Diagnostic Logger Server (Threaded) ==={COLOR_RESET}")
    print(f"Listening on: {COLOR_CYAN}http://127.0.0.1:{PORT}{COLOR_RESET}")
    print(f"Writing to:   {COLOR_CYAN}{LOG_FILE}{COLOR_RESET}")
    print(f"Endpoints:    {COLOR_GRAY}POST /log, GET /logs, POST /clear{COLOR_RESET}\n", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down logger server.")
        httpd.server_close()


if __name__ == "__main__":
    run()
