"""Unstructured partition_pdf with the hi_res strategy and table structure inference."""

from importlib.metadata import version

from _common import run


def setup(device, options):
    from unstructured.partition.pdf import partition_pdf

    return partition_pdf


def _render(el) -> str:
    category = getattr(el, "category", "")
    if category == "Table":
        html = getattr(el.metadata, "text_as_html", None)
        return html or el.text
    if category == "Title":
        return f"## {el.text}"
    if category == "ListItem":
        return f"- {el.text}"
    return el.text


def convert(partition_pdf, path, num_pages):
    elements = partition_pdf(filename=path, strategy="hi_res", infer_table_structure=True)
    pages = [[] for _ in range(num_pages)]
    for el in elements:
        page = (getattr(el.metadata, "page_number", None) or 1) - 1
        if 0 <= page < num_pages and el.text and el.text.strip():
            pages[page].append(_render(el))
    return ["\n\n".join(p) for p in pages]


if __name__ == "__main__":
    # hi_res runs its layout model with onnxruntime on the CPU.
    run(setup, convert, version("unstructured"), device="cpu")
