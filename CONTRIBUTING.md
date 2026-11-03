# Contributing

Thanks for helping. Bug reports with a PDF that reproduces the problem (one you are allowed to share)
are the most useful contribution.

## Setup

```bash
git clone https://github.com/diegoperezg7/parsearena && cd parsearena
uv sync
uv run pytest            # fast tests; no parser models are downloaded
uv run ruff check . && uv run ruff format --check .
```

The tests install only the pypdf baseline into an isolated environment. Running the real parsers
downloads several GB, so it is not part of CI.

## Adding a parser

1. Add a `ParserSpec` in `src/parsearena/parsers.py` with exact `==` pins.
2. Add `src/parsearena/runners/run_<name>.py`. It runs inside the parser's own environment, so it may
   import only the standard library, `_common` and the parser itself. Return one string per page.
3. Use the parser's default settings unless there is a documented reason not to, and say so in the README.
4. Re-record the demo with `scripts/record_demo.py` if the parser should appear there.

## Pull requests

Keep them small and focused, add a test for the behaviour you change, and describe how you checked it.
