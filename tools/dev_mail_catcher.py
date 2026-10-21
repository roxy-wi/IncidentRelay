"""Minimal local SMTP catcher for IncidentRelay development.

Accepts SMTP on 127.0.0.1:1025, never forwards anything, and prints each
received message plus writes it to logs/local-mail/. Dependency-free.

Run:  .venv/bin/python tools/dev_mail_catcher.py
"""

import asyncio
import email
import email.policy
import os
from datetime import datetime

HOST = os.getenv("MAIL_CATCHER_HOST", "127.0.0.1")
PORT = int(os.getenv("MAIL_CATCHER_PORT", "1025"))
OUT_DIR = os.getenv("MAIL_CATCHER_DIR", "logs/local-mail")

os.makedirs(OUT_DIR, exist_ok=True)

_counter = 0


def _render(raw_bytes):
    """Return a short human summary of one received message."""
    message = email.message_from_bytes(
        raw_bytes,
        policy=email.policy.default,
    )

    body = ""
    if message.is_multipart():
        for part in message.walk():
            if part.get_content_type() == "text/plain":
                body = part.get_content()
                break
    else:
        try:
            body = message.get_content()
        except Exception:
            body = raw_bytes.decode("utf-8", "replace")

    return message, body


async def handle_client(reader, writer):
    global _counter

    peer = writer.get_extra_info("peername")

    async def send(line):
        writer.write((line + "\r\n").encode())
        await writer.drain()

    await send("220 localhost IncidentRelay dev mail catcher")

    recipients = []
    sender = None

    try:
        while True:
            raw = await reader.readline()

            if not raw:
                break

            line = raw.decode("utf-8", "replace").strip()
            upper = line.upper()

            if upper.startswith("EHLO") or upper.startswith("HELO"):
                await send("250-localhost")
                await send("250 SIZE 10485760")
            elif upper.startswith("MAIL FROM"):
                sender = line.partition(":")[2].strip()
                await send("250 OK")
            elif upper.startswith("RCPT TO"):
                recipients.append(line.partition(":")[2].strip())
                await send("250 OK")
            elif upper == "DATA":
                await send("354 End data with <CR><LF>.<CR><LF>")

                chunks = []
                while True:
                    data_line = await reader.readline()

                    if not data_line:
                        break

                    if data_line in (b".\r\n", b".\n"):
                        break

                    if data_line.startswith(b".."):
                        data_line = data_line[1:]

                    chunks.append(data_line)

                raw_message = b"".join(chunks)
                _counter += 1

                message, body = _render(raw_message)
                stamp = datetime.now().strftime("%H:%M:%S")

                print()
                print("=" * 72)
                print(f"MAIL #{_counter}  {stamp}")
                print("=" * 72)
                print(f"From    : {message.get('From') or sender}")
                print(f"To      : {message.get('To') or ', '.join(recipients)}")
                print(f"Subject : {message.get('Subject')}")
                print("-" * 72)
                print(body.strip())
                print("=" * 72)
                print(flush=True)

                path = os.path.join(
                    OUT_DIR,
                    f"{_counter:04d}-{datetime.now():%Y%m%d-%H%M%S}.eml",
                )
                with open(path, "wb") as fh:
                    fh.write(raw_message)

                recipients = []
                await send("250 OK: queued")
            elif upper == "QUIT":
                await send("221 Bye")
                break
            elif upper == "RSET":
                recipients = []
                sender = None
                await send("250 OK")
            elif upper == "NOOP":
                await send("250 OK")
            else:
                await send("250 OK")
    except (ConnectionResetError, asyncio.IncompleteReadError):
        pass
    finally:
        try:
            writer.close()
        except Exception:
            pass


async def main():
    server = await asyncio.start_server(handle_client, HOST, PORT)

    print(f"dev mail catcher listening on {HOST}:{PORT}")
    print(f"saving messages to {OUT_DIR}/")
    print("waiting for mail...", flush=True)

    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nmail catcher stopped")
