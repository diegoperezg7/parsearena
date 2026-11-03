"""Docling with its default PDF pipeline (layout, table structure, automatic OCR)."""

from importlib.metadata import version

from _common import run


def setup(device, options):
    from docling.datamodel.accelerator_options import AcceleratorOptions
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions
    from docling.document_converter import DocumentConverter, PdfFormatOption

    opts = PdfPipelineOptions()
    opts.accelerator_options = AcceleratorOptions(device=device)
    return DocumentConverter(format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opts)})


def convert(converter, path, num_pages):
    doc = converter.convert(path).document
    return [doc.export_to_markdown(page_no=i) for i in range(1, num_pages + 1)]


if __name__ == "__main__":
    run(setup, convert, version("docling"))
