"""Pillar 2 — Memory (the temporal anchor).

Provides continuity across steps and sessions from a single embedded store:
SQLite for relational state + sqlite-vec for vectors. Embeddings default to a local
sentence-transformers model (fully offline).

    Working  — the context window; sliding window + recursive summarization
    Episodic — append-only trace of past runs ("flight data recorder"); similar-task
               lookup injects warnings on new tasks
    Semantic — user/domain knowledge; RAG retrieval

Modules (Phase 4+):
    store.py       — SQLite schema + sqlite-vec index
    working.py     — working-memory manager
    episodic.py    — episodic traces
    semantic.py    — semantic / RAG
    embeddings.py  — Embedder ABC + sentence-transformers default
"""
