"""Fake parser runner used by the tests (standard library only)."""

import os
import subprocess
import sys

from _common import run


def setup(device, options):
    return os.environ.get("FAKE_MODE", "ok")


def _spawn_helper():
    """Start a long-lived helper in its own session, like Marker's Surya servers."""
    helper = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(300)"], start_new_session=True)
    with open(os.environ["FAKE_PIDFILE"], "w") as fh:
        fh.write(str(helper.pid))


def convert(mode, path, num_pages):
    if mode in ("spawn", "spawn-hang"):
        _spawn_helper()
    if mode == "spawn-hang":
        import time

        time.sleep(300)
    if mode == "crash":
        sys.exit(3)
    if mode == "hang":
        import time

        time.sleep(30)
    if "bad" in os.path.basename(path):
        raise ValueError("cannot read this one")
    return [f"page {i + 1} of {os.path.basename(path)}" for i in range(num_pages)]


if __name__ == "__main__":
    run(setup, convert, "0.0-test")
