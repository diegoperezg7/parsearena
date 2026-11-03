# Security policy

## Reporting a vulnerability

Please report security issues privately through
[GitHub security advisories](https://github.com/diegoperezg7/parsearena/security/advisories/new).
Do not open a public issue. You will get an answer within a week.

## What parsearena does with your data

- PDFs are parsed locally. Parsers run as subprocesses in their own virtual environments.
- Parser packages and model weights are downloaded from PyPI and Hugging Face on first use.
- API keys are read only from environment variables and are only sent to the provider you select
  with `--gen-questions --provider`. With `--provider ollama` nothing leaves your machine.
- parsearena has no telemetry. MinerU ships its own telemetry; parsearena sets
  `MINERU_TELEMETRY_DISABLED=1` when it runs MinerU.
