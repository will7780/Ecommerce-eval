"""Ephemeral offline server used by Playwright verification."""

from __future__ import annotations

import os
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from fastapi.routing import APIRoute
import tempfile
from pathlib import Path

import uvicorn

from commerce_eval.api import create_app
from commerce_eval.demo import seed_demo
from commerce_eval.storage import Database, Repository


def main() -> None:
    os.environ["COMMERCE_EVAL_DISABLE_CENTRAL_ENV"] = "1"
    for name in tuple(os.environ):
        if name.endswith("_API_KEY"):
            os.environ.pop(name)
    database_path = Path(tempfile.gettempdir()) / f"commerce-agent-eval-e2e-{os.getpid()}.db"
    database = Database(database_path)
    database.initialize()
    seed_demo(Repository(database))
    class TargetHandler(BaseHTTPRequestHandler):
        executions = 0

        def log_message(self, format, *args):
            pass

        def do_GET(self):
            body = json.dumps({"protocol_version": "1.1", "operations": ["start", "resume"], "safe_for_eval": True}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            type(self).executions += 1
            self.send_error(405)

    target = ThreadingHTTPServer(("127.0.0.1", 0), TargetHandler)
    worker = threading.Thread(target=target.serve_forever, daemon=True)
    worker.start()
    app = create_app(database_path=database_path)

    def test_target():
        return {"url": f"http://127.0.0.1:{target.server_port}", "executions": TargetHandler.executions}

    app.router.routes.insert(0, APIRoute("/api/v1/test-target", test_target, methods=["GET"]))
    try:
        uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("EVAL_E2E_PORT", "8770")), log_level="warning")
    finally:
        target.shutdown()
        target.server_close()
        app.state.database.engine.dispose()
        database.engine.dispose()


if __name__ == "__main__":
    main()
