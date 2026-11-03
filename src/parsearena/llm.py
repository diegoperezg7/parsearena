"""One OpenAI-compatible client for every provider, with a hard spending cap."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field

from .errors import BudgetExceeded, UserError


@dataclass(frozen=True)
class Preset:
    base_url: str
    key_env: str | None
    model: str
    price_in: float  # USD per million input tokens (estimate used for the pre-call check)
    price_out: float  # USD per million output tokens


PRESETS: dict[str, Preset] = {
    "ollama": Preset("http://localhost:11434/v1", None, "qwen3:4b", 0.0, 0.0),
    "openrouter": Preset(
        "https://openrouter.ai/api/v1", "OPENROUTER_API_KEY", "deepseek/deepseek-v4.1-flash", 0.045, 0.50
    ),
    "openai": Preset("https://api.openai.com/v1", "OPENAI_API_KEY", "gpt-5.6-luna", 0.20, 1.20),
    "mistral": Preset("https://api.mistral.ai/v1", "MISTRAL_API_KEY", "mistral-small-latest", 0.10, 0.30),
}


def ollama_base_url() -> str:
    host = os.environ.get("OLLAMA_HOST", "").strip()
    if not host:
        return PRESETS["ollama"].base_url
    if not host.startswith(("http://", "https://")):
        host = f"http://{host}"
    return host.rstrip("/") + "/v1"


@dataclass
class LLM:
    provider: str
    model: str
    max_cost: float = 1.0
    price_in: float | None = None
    price_out: float | None = None
    spent: float = 0.0
    calls: int = 0
    _client: object = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if self.provider not in PRESETS:
            raise UserError(f"Unknown provider: {self.provider}", f"Choose one of: {', '.join(PRESETS)}")
        preset = PRESETS[self.provider]
        self.model = self.model or preset.model
        if self.price_in is None:
            self.price_in = preset.price_in
        if self.price_out is None:
            self.price_out = preset.price_out
        if preset.key_env:
            key = os.environ.get(preset.key_env, "").strip()
            if not key:
                raise UserError(
                    f"Missing API key: set {preset.key_env}.",
                    f"Example: export {preset.key_env}=...  or use --provider ollama for a free local model.",
                )
            base_url = preset.base_url
        else:
            key, base_url = "ollama", ollama_base_url()
        from openai import OpenAI

        self.base_url = base_url
        self.timeout = float(os.environ.get("PARSEARENA_LLM_TIMEOUT", "300"))
        self._client = OpenAI(base_url=base_url, api_key=key, max_retries=0, timeout=self.timeout)

    @property
    def local(self) -> bool:
        return self.provider == "ollama"

    def estimate(self, prompt: str, max_tokens: int) -> float:
        tokens_in = len(prompt) / 3.5
        return (tokens_in * self.price_in + max_tokens * self.price_out) / 1e6

    def complete(self, system: str, prompt: str, max_tokens: int = 2000) -> str:
        if not self.local:
            projected = self.spent + self.estimate(system + prompt, max_tokens)
            if projected > self.max_cost:
                raise BudgetExceeded(
                    f"Budget exceeded: the next call could bring spend to ${projected:.4f}, "
                    f"over --max-cost ${self.max_cost:.2f}.",
                    "Partial results were kept. Raise --max-cost or use --provider ollama.",
                )
        extra = {"usage": {"include": True}} if self.provider == "openrouter" else None
        resp = self._call(system, prompt, max_tokens, extra)
        self.calls += 1
        self.spent += self._cost(resp)
        return (resp.choices[0].message.content or "").strip()

    def _call(self, system, prompt, max_tokens, extra):
        import openai

        delay = 2.0
        for attempt in range(5):
            try:
                return self._client.chat.completions.create(
                    model=self.model,
                    messages=[{"role": "system", "content": system}, {"role": "user", "content": prompt}],
                    max_tokens=max_tokens,
                    temperature=0.2,
                    extra_body=extra,
                )
            except openai.APITimeoutError as exc:
                if self.local or attempt == 4:
                    raise UserError(
                        f"{self.provider} did not answer within {self.timeout:.0f}s.",
                        "The server may be busy or still loading the model. Try again, "
                        "or raise the limit with PARSEARENA_LLM_TIMEOUT (seconds).",
                    ) from exc
            except openai.APIConnectionError as exc:
                if self.local:
                    raise UserError(
                        f"Ollama is not reachable at {self.base_url}.",
                        "Start it with `ollama serve`, or set OLLAMA_HOST.",
                    ) from exc
                if attempt == 4:
                    raise UserError(f"Could not reach {self.provider}: {exc}") from exc
            except openai.AuthenticationError as exc:
                raise UserError(
                    f"{self.provider} rejected the API key.", f"Check {PRESETS[self.provider].key_env}."
                ) from exc
            except openai.NotFoundError as exc:
                hint = f"Pull it with `ollama pull {self.model}`." if self.local else "Check --model."
                raise UserError(f"Model not found on {self.provider}: {self.model}", hint) from exc
            except (openai.RateLimitError, openai.InternalServerError) as exc:
                if attempt == 4:
                    raise UserError(f"{self.provider} keeps failing: {exc}", "Try again later.") from exc
            time.sleep(delay)
            delay *= 2
        raise UserError(f"{self.provider} did not answer.")

    def _cost(self, resp) -> float:
        if self.local:
            return 0.0
        usage = getattr(resp, "usage", None)
        if usage is None:
            return 0.0
        reported = getattr(usage, "cost", None)
        if reported is None and getattr(usage, "model_extra", None):
            reported = usage.model_extra.get("cost")
        if reported is not None:
            return float(reported)
        return (
            (usage.prompt_tokens or 0) * self.price_in + (usage.completion_tokens or 0) * self.price_out
        ) / 1e6
