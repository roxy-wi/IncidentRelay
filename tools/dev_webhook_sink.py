"""Minimal local webhook sink for IncidentRelay development.

Listens on 127.0.0.1:9000 and pretty-prints every JSON payload it receives,
so a Slack channel in incoming-webhook mode can be pointed at it to inspect
the rendered Block Kit message (including `<@USER_ID>` mentions) without a
real Slack workspace.

Run:  .venv/bin/python tools/dev_webhook_sink.py
Then set the Slack channel webhook_url to http://127.0.0.1:9000/slack
"""

import json
import os
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOST = os.getenv("WEBHOOK_SINK_HOST", "127.0.0.1")
PORT = int(os.getenv("WEBHOOK_SINK_PORT", "9000"))
OUT_DIR = os.getenv("WEBHOOK_SINK_DIR", "logs/local-webhooks")

os.makedirs(OUT_DIR, exist_ok=True)

_counter = 0


def extract_mentions(payload):
    """Return every Slack mention found anywhere in the payload."""
    raw = json.dumps(payload)
    mentions = []
    index = 0

    while True:
        start = raw.find("<@", index)

        if start == -1:
            break

        end = raw.find(">", start)

        if end == -1:
            break

        mentions.append(raw[start:end + 1])
        index = end + 1

    return mentions


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        global _counter

        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""

        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"ok")

        _counter += 1
        stamp = datetime.now().strftime("%H:%M:%S")

        try:
            payload = json.loads(body)
        except ValueError:
            payload = {"_raw": body.decode("utf-8", "replace")}

        print()
        print("=" * 72)
        print(f"WEBHOOK #{_counter}  {stamp}  {self.path}")
        print("=" * 72)

        text = payload.get("text")
        if text:
            print(f"text: {text[:200]}")

        for block in payload.get("blocks", []) or []:
            if block.get("type") == "header":
                print(f"header: {block['text']['text']}")
            elif block.get("type") == "section" and block.get("fields"):
                for field in block["fields"]:
                    label, _, value = field["text"].partition("\n")
                    print(f"  {label.strip('*'):<10} = {value}")

        mentions = extract_mentions(payload)
        print(f"mentions: {mentions or '(none)'}")
        print("=" * 72, flush=True)

        path = os.path.join(OUT_DIR, f"{_counter:04d}-{datetime.now():%H%M%S}.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, ensure_ascii=False)

    def log_message(self, *args):
        return


if __name__ == "__main__":
    server = ThreadingHTTPServer((HOST, PORT), Handler)

    print(f"dev webhook sink listening on http://{HOST}:{PORT}")
    print(f"saving payloads to {OUT_DIR}/")
    print("waiting for webhooks...", flush=True)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nwebhook sink stopped")
