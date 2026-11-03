"""Fake parser runner used by the tests (standard library only)."""

import os
import sys

from _common import run


def setup(device, options):
    return os.environ.get("FAKE_MODE", "ok")


def convert(mode, path, num_pages):
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
