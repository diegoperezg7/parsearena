import httpx
import openai
import pytest

from parsearena.errors import BudgetExceeded, UserError
from parsearena.llm import LLM, ollama_base_url


def test_missing_key_names_the_variable(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(UserError, match="OPENROUTER_API_KEY"):
        LLM(provider="openrouter", model="")


def test_unknown_provider():
    with pytest.raises(UserError, match="Unknown provider"):
        LLM(provider="nope", model="")


def test_ollama_host_override(monkeypatch):
    monkeypatch.setenv("OLLAMA_HOST", "10.0.0.2:11434")
    assert ollama_base_url() == "http://10.0.0.2:11434/v1"
    monkeypatch.delenv("OLLAMA_HOST")
    assert ollama_base_url() == "http://localhost:11434/v1"


class _Usage:
    def __init__(self, cost=None):
        self.prompt_tokens, self.completion_tokens, self.cost, self.model_extra = 1000, 100, cost, {}


class _Resp:
    def __init__(self, text="ok", cost=None):
        msg = type("M", (), {"content": text})
        self.choices = [type("C", (), {"message": msg})]
        self.usage = _Usage(cost)


class _Client:
    def __init__(self, behaviour):
        self.behaviour = behaviour
        self.chat = type("Chat", (), {"completions": self})()

    def create(self, **kwargs):
        return self.behaviour(**kwargs)


def _paid(monkeypatch, behaviour, max_cost=1.0):
    monkeypatch.setenv("MISTRAL_API_KEY", "test-key")
    llm = LLM(provider="mistral", model="", max_cost=max_cost)
    llm._client = _Client(behaviour)
    monkeypatch.setattr("time.sleep", lambda s: None)
    return llm


def test_budget_checked_before_the_call(monkeypatch):
    called = []
    llm = _paid(monkeypatch, lambda **k: called.append(1) or _Resp(), max_cost=0.0)
    with pytest.raises(BudgetExceeded, match="max-cost"):
        llm.complete("sys", "prompt " * 100)
    assert called == []


def test_spend_uses_token_prices_and_reported_cost(monkeypatch):
    llm = _paid(monkeypatch, lambda **k: _Resp())
    assert llm.complete("s", "p") == "ok"
    assert llm.spent == pytest.approx((1000 * 0.10 + 100 * 0.30) / 1e6)
    llm._client = _Client(lambda **k: _Resp(cost=0.5))
    llm.complete("s", "p")
    assert llm.spent == pytest.approx(0.5 + (1000 * 0.10 + 100 * 0.30) / 1e6)


def _req():
    return httpx.Request("POST", "http://x/v1/chat/completions")


def test_model_not_found_is_user_error(monkeypatch):
    def boom(**k):
        raise openai.NotFoundError("missing", response=httpx.Response(404, request=_req()), body=None)

    llm = _paid(monkeypatch, boom)
    with pytest.raises(UserError, match="Model not found"):
        llm.complete("s", "p")


def test_bad_key_is_user_error(monkeypatch):
    def boom(**k):
        raise openai.AuthenticationError("no", response=httpx.Response(401, request=_req()), body=None)

    with pytest.raises(UserError, match="rejected the API key"):
        _paid(monkeypatch, boom).complete("s", "p")


def test_rate_limit_retries_then_succeeds(monkeypatch):
    calls = []

    def flaky(**k):
        calls.append(1)
        if len(calls) < 3:
            raise openai.RateLimitError("slow down", response=httpx.Response(429, request=_req()), body=None)
        return _Resp("fine")

    assert _paid(monkeypatch, flaky).complete("s", "p") == "fine"
    assert len(calls) == 3


def test_ollama_unreachable_is_user_error(monkeypatch):
    monkeypatch.setenv("OLLAMA_HOST", "http://127.0.0.1:9")
    llm = LLM(provider="ollama", model="qwen3:4b")
    with pytest.raises(UserError, match="Ollama is not reachable"):
        llm.complete("s", "p", max_tokens=5)


def test_local_model_is_free_and_never_blocked(monkeypatch):
    llm = LLM(provider="ollama", model="qwen3:4b", max_cost=0.0)
    llm._client = _Client(lambda **k: _Resp("hi"))
    assert llm.complete("s", "p") == "hi"
    assert llm.spent == 0.0


def test_timeout_is_not_reported_as_unreachable(monkeypatch):
    def slow(**k):
        raise openai.APITimeoutError(request=_req())

    llm = LLM(provider="ollama", model="qwen3:4b")
    llm._client = _Client(slow)
    with pytest.raises(UserError, match="did not answer within"):
        llm.complete("s", "p")
