"""Jobs that run on a clock while the server is up.

Under Docker's restart policy the server can run for weeks, so anything that only
happened at startup - like expiring old recordings - effectively never happened. One
loop wakes every few minutes and runs every job; each job is either cheap enough to run
every time or checks for itself whether it is due.
"""

import asyncio

from . import settings, store

TICK_SECONDS = 600


def expire_recordings() -> None:
    gone = store.purge_audio(settings.get("audio_retention_days"))
    if gone:
        print(f"  expired {gone} recording(s)")


JOBS = [expire_recordings]


async def run() -> None:
    while True:
        for job in JOBS:
            try:
                job()
            except Exception as exc:  # one failing job must not stop the others
                print(f"  {job.__name__} failed: {exc}")
        await asyncio.sleep(TICK_SECONDS)
