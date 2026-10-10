"""Serves the real cab page and a stream that sends one advisory and then falls silent (a dead link)."""

import json
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

STATIC = Path(sys.argv[1])
ADVISORY = {
    "run": "TEST1@0",
    "train": "TEST1 Stand-in train (not a real train)",
    "type": "Exp",
    "status": "NORMAL",
    "position_evidence": "FRESH",
    "position": {
        "state": "RUNNING",
        "from_node": "AAA",
        "to_node": "BBB",
        "offset_km": 3.2,
        "speed_kmph": 96.0,
        "section_id": "AAA-BBB",
        "index": 0,
    },
    "advisory_speed_band_kmph": [99, 110],
    "route_ahead": ["AAA-BBB"],
    "next_station": "BBB",
    "schedule_deviation_min": 0.0,
    "arrival": "08:35",
    "plan_source": "PUBLISHED TIMETABLE",
    "nearby_trains": [],
    "threats": [],
    "authority": "ADVISORY_ONLY",
    "footer": "ADVISORY PROTOTYPE",
}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/cab":
            return self.file(STATIC / "cab.html", "text/html")
        if path.startswith("/railguard/static/"):
            name = path.rsplit("/", 1)[1]
            return self.file(STATIC / name, "text/javascript" if name.endswith(".js") else "text/css")
        if path.endswith("/stream"):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            self.wfile.write(b"retry: 3000\n\n")
            self.wfile.write(f"id: 1\nevent: advisory\ndata: {json.dumps(ADVISORY)}\n\n".encode())
            self.wfile.flush()
            time.sleep(120)  # then silence: no advisory, no heartbeat, connection left open
            return
        self.send_response(404)
        self.end_headers()

    def file(self, p, kind):
        body = p.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


ThreadingHTTPServer(("127.0.0.1", int(sys.argv[2])), Handler).serve_forever()
