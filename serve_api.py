"""Local API for the quote review screen. POST /api/normalize {\"text\": \"...\"}."""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from automate import ingest_text
from quote_agent import parse_freight_quote


class Handler(BaseHTTPRequestHandler):
    def _cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_POST(self) -> None:
        path = self.path.split("?", 1)[0]
        if path not in {"/api/normalize", "/api/intake"}:
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw.decode("utf-8"))
            text = body.get("text") or ""
            if path == "/api/intake":
                payload = ingest_text(
                    text,
                    business_id=body.get("business_id"),
                    email_from=body.get("email_from"),
                    telegram_chat_id=body.get("telegram_chat_id"),
                )
            else:
                payload = parse_freight_quote(text).model_dump()
            status = 200
        except Exception as exc:  # noqa: BLE001 — return a client-visible error
            payload = {"error": str(exc)}
            status = 400
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self._cors()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt: str, *args) -> None:
        print(f"[api] {self.address_string()} {fmt % args}")


def main() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 8787), Handler)
    print("Quote API on http://127.0.0.1:8787")
    server.serve_forever()


if __name__ == "__main__":
    main()
