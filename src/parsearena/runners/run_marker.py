"""Marker with its default models, markdown output, paginated so pages can be aligned."""

import re
from importlib.metadata import version

from _common import run

SEP = re.compile(r"\n*\{(\d+)\}-{10,}\n*")


def setup(device, options):
    import os

    if device != "auto":
        os.environ.setdefault("TORCH_DEVICE", device)
    from marker.config.parser import ConfigParser
    from marker.converters.pdf import PdfConverter
    from marker.models import create_model_dict

    config = ConfigParser(
        {"output_format": "markdown", "paginate_output": True, "disable_image_extraction": True}
    )
    return PdfConverter(
        artifact_dict=create_model_dict(),
        processor_list=config.get_processors(),
        renderer=config.get_renderer(),
        config=config.generate_config_dict(),
    )


def convert(converter, path, num_pages):
    text = converter(path).markdown
    pages = [""] * num_pages
    parts = SEP.split(text)
    # parts = [before, id0, text0, id1, text1, ...]
    for i in range(1, len(parts) - 1, 2):
        idx = int(parts[i])
        if 0 <= idx < num_pages:
            pages[idx] = parts[i + 1].strip()
    if len(parts) == 1:
        pages[0] = text
    return pages


if __name__ == "__main__":

    def teardown():
        # Marker 2.x starts Surya inference servers (layout, OCR error, llama.cpp);
        # stop them before the runner exits.
        from marker.models import shutdown_models

        shutdown_models()

    run(setup, convert, version("marker-pdf"), teardown=teardown)
