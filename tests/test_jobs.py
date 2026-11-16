from __future__ import annotations

import http.server
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from assistant.db import Database
from assistant.jobs_core import fetch_page

PAGE = b"<html><head><title>Order 42</title><style>x{}</style></head><body><h1>Status</h1><p>Shipped</p><script>no()</script></body></html>"


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(PAGE)

    def log_message(self, *args):
        pass


class FetchTests(unittest.TestCase):
    def test_reads_text_without_scripts(self) -> None:
        server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            with mock.patch.dict(os.environ, {"NO_PROXY": "127.0.0.1", "no_proxy": "127.0.0.1"}):
                text = fetch_page(f"http://127.0.0.1:{server.server_port}/")
        finally:
            server.shutdown()
        self.assertIn("Title: Order 42", text)
        self.assertIn("Shipped", text)
        self.assertNotIn("no()", text)
        self.assertIn("Only http", fetch_page("file:///etc/passwd"))


class JobStoreTests(unittest.TestCase):
    def test_add_update_cancel(self) -> None:
        from datetime import datetime, timezone

        with tempfile.TemporaryDirectory() as folder:
            db = Database(Path(folder) / "a.db")
            job = db.add_job(1, "check page", 60, datetime(2030, 1, 1, tzinfo=timezone.utc))
            self.assertEqual(len(db.due_jobs(datetime(2030, 1, 1, 0, 1, tzinfo=timezone.utc))), 1)
            db.update_job(job["id"], memory="Shipped", failures=0)
            self.assertEqual(db.get_job(1, job["id"])["memory"], "Shipped")
            self.assertIsNotNone(db.cancel_job(1, job["id"]))
            self.assertEqual(db.list_jobs(1), [])
            db.close()
