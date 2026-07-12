"""Embeddings (Pillar 2).

The default is a local ``sentence-transformers`` model (fully offline). Because that pulls
in torch — a heavy dependency not always installed — :func:`build_embedder` falls back to a
dependency-free :class:`HashingEmbedder` so semantic memory still functions (and tests run)
without the ``local`` extra. Use ``hash:<dim>`` explicitly to force the fallback.
"""

from __future__ import annotations

import hashlib
import math
import re
from abc import ABC, abstractmethod

_TOKEN = re.compile(r"[a-z0-9]+")


class Embedder(ABC):
    """Turns text into unit-norm vectors."""

    dim: int = 0
    spec: str = ""

    @abstractmethod
    def encode(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError

    def encode_one(self, text: str) -> list[float]:
        return self.encode([text])[0]


class HashingEmbedder(Embedder):
    """Deterministic hashing embedder — no ML deps, stable across runs.

    Hashes word tokens into ``dim`` signed buckets and L2-normalizes. Good enough for
    near-duplicate and keyword-overlap recall; not semantically rich like a trained model.
    """

    def __init__(self, dim: int = 256):
        self.dim = dim
        self.spec = f"hash:{dim}"

    def encode(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]

    def _vec(self, text: str) -> list[float]:
        v = [0.0] * self.dim
        for tok in _TOKEN.findall(text.lower()):
            digest = hashlib.md5(tok.encode("utf-8")).digest()
            idx = int.from_bytes(digest[:4], "little") % self.dim
            sign = 1.0 if digest[4] & 1 else -1.0
            v[idx] += sign
        norm = math.sqrt(sum(x * x for x in v))
        if norm == 0.0:
            return v
        return [x / norm for x in v]


class SentenceTransformerEmbedder(Embedder):
    """Local transformer embeddings via sentence-transformers (offline)."""

    def __init__(self, model_name: str):
        from sentence_transformers import SentenceTransformer  # heavy import, lazy

        self._model = SentenceTransformer(model_name)
        # Method was renamed get_sentence_embedding_dimension -> get_embedding_dimension.
        get_dim = getattr(
            self._model, "get_embedding_dimension", None
        ) or self._model.get_sentence_embedding_dimension
        self.dim = int(get_dim())
        self.spec = f"sentence-transformers:{model_name}"

    def encode(self, texts: list[str]) -> list[list[float]]:
        vecs = self._model.encode(texts, normalize_embeddings=True)
        return [list(map(float, row)) for row in vecs]


def build_embedder(spec: str, *, allow_fallback: bool = True) -> tuple[Embedder, str | None]:
    """Construct an embedder from a spec string.

    Returns ``(embedder, note)`` where ``note`` is a human-readable fallback message when the
    requested embedder was unavailable, else ``None``.
    """
    scheme, _, name = spec.partition(":")
    scheme = scheme.strip()

    if scheme == "hash":
        dim = int(name) if name.strip().isdigit() else 256
        return HashingEmbedder(dim), None

    if scheme == "sentence-transformers":
        try:
            return SentenceTransformerEmbedder(name or "all-MiniLM-L6-v2"), None
        except Exception as exc:  # ImportError, model download failure, etc.
            if not allow_fallback:
                raise
            return (
                HashingEmbedder(256),
                f"sentence-transformers unavailable ({type(exc).__name__}); "
                "using the offline hash embedder. Install with: pip install \"agent86[local]\".",
            )

    if allow_fallback:
        return HashingEmbedder(256), f"unknown embedder '{spec}'; using hash embedder."
    raise ValueError(f"Unknown embedder spec: {spec!r}")


__all__ = [
    "Embedder",
    "HashingEmbedder",
    "SentenceTransformerEmbedder",
    "build_embedder",
]
