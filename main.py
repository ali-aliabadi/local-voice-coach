"""Spoken English practice that measures your hesitation.

Local, private, free. Whisper and Kokoro run on this machine; only transcript text ever
reaches a model, and only if you pick a cloud backend.

    python main.py                 open http://127.0.0.1:8000
    python main.py --port 9000
    python main.py --host 0.0.0.0  see the warning below
"""

import argparse
import socket
import threading
import time
import webbrowser

import uvicorn

BANNER = """
  speaking practice · local, private
  ─────────────────────────────────────
"""


def open_when_up(url: str, host: str, port: int) -> None:
    """Open the browser once the server answers.

    It only listens after Whisper and Kokoro load, which on a first run means downloading
    Whisper; a fixed delay opened a dead page minutes early.
    """

    def wait() -> None:
        while True:
            try:
                socket.create_connection((host, port), timeout=1).close()
                break
            except OSError:
                time.sleep(0.5)
        webbrowser.open(url)

    threading.Thread(target=wait, daemon=True).start()


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Anything but 127.0.0.1 exposes your microphone feed to your network, and "
        "browsers block getUserMedia on plain http from another host anyway. Requests are "
        "only accepted for localhost names; add yours with ALLOWED_HOSTS=name1,name2.",
    )
    parser.add_argument("--no-open", action="store_true", help="don't open a browser")
    args = parser.parse_args()

    url = f"http://{args.host}:{args.port}"
    print(BANNER)
    if args.host != "127.0.0.1":
        print("  ! serving beyond localhost. Microphone access needs https from another device.\n")
    print(f"  {url}\n")
    if not args.no_open:
        open_when_up(url, args.host, args.port)

    uvicorn.run("coach.server.app:app", host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
