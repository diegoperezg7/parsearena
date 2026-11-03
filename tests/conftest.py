import numpy as np
import pytest


class FakeEmbedder:
    """Bag-of-letters embedding: deterministic, offline, good enough for ranking tests."""

    name = "fake"

    def _vec(self, text):
        v = np.zeros(26, dtype=np.float32)
        for ch in text.lower():
            if "a" <= ch <= "z":
                v[ord(ch) - 97] += 1
        n = np.linalg.norm(v)
        return v / n if n else v

    def embed(self, texts):
        return np.array([self._vec(t) for t in texts])

    def embed_queries(self, texts):
        return self.embed(texts)


@pytest.fixture
def fake_embedder():
    return FakeEmbedder()


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("PARSEARENA_HOME", str(tmp_path / "home"))
