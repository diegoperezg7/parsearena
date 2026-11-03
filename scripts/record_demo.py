"""Build src/parsearena/demo/recorded.json from one or more `parsearena run` output dirs.

Usage:
    uv run parsearena run src/parsearena/demo/pdfs/*.pdf --out runs/all --no-open
    uv run python scripts/record_demo.py runs/all [runs/other ...]

Later directories override parsers from earlier ones, so a single parser can be
re-recorded without running the others again.
"""

import json
import sys
from pathlib import Path

DOCS = {
    "census-income-2023": {
        "title": "U.S. Census Bureau, Income in the United States: 2023 (P60-282), pp. 1, 2, 15",
        "license": "Public domain (U.S. government work)",
        "source": "https://www.census.gov/library/publications/2024/demo/p60-282.html",
    },
    "dpo-arxiv-2305.18290": {
        "title": "Rafailov et al., Direct Preference Optimization (arXiv:2305.18290v3), pp. 1, 4, 5, 9",
        "license": "CC BY 4.0",
        "source": "https://arxiv.org/abs/2305.18290",
    },
    "naca-report-1135-scan": {
        "title": "NACA Report 1135 (1953), p. 613, image-only scan",
        "license": "Public domain (U.S. government work)",
        "source": "https://ntrs.nasa.gov/citations/19930091059",
    },
}

ORDER = ["docling", "marker", "mineru", "unstructured", "pypdf"]


def main() -> None:
    merged = None
    for d in sys.argv[1:]:
        data = json.loads((Path(d) / "outputs.json").read_text())
        if merged is None:
            merged = data
            continue
        known = {p["name"] for p in merged["parsers"]}
        for p in data["parsers"]:
            if p["name"] in known:
                merged["parsers"] = [q for q in merged["parsers"] if q["name"] != p["name"]]
            merged["parsers"].append(p)
            merged["outputs"][p["name"]] = data["outputs"][p["name"]]
        merged["meta"]["created"] = max(merged["meta"]["created"], data["meta"]["created"])
    merged["parsers"].sort(key=lambda p: ORDER.index(p["name"]) if p["name"] in ORDER else 99)
    merged["outputs"] = {p["name"]: merged["outputs"][p["name"]] for p in merged["parsers"]}
    for doc in merged["docs"]:
        doc.update(DOCS.get(doc["id"], {}))
    for per in merged["outputs"].values():
        for out in per.values():
            out.get("extra", {}).pop("wall_seconds", None)
    out = Path("src/parsearena/demo/recorded.json")
    out.write_text(json.dumps(merged, ensure_ascii=False, indent=1) + "\n")
    print(f"wrote {out} with parsers: {', '.join(p['name'] for p in merged['parsers'])}")


if __name__ == "__main__":
    main()
