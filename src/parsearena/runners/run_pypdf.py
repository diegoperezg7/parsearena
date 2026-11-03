"""pypdf baseline: the text layer of each page, nothing else."""

import logging
from importlib.metadata import version

from _common import run

logging.disable(logging.WARNING)


def setup(device, options):
    return None


def convert(state, path, num_pages):
    from pypdf import PdfReader

    return [page.extract_text() or "" for page in PdfReader(path).pages]


if __name__ == "__main__":
    run(setup, convert, version("pypdf"), device="cpu")
