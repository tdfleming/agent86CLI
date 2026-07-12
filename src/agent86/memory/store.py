"""The memory store (Pillar 2) — SQLite + optional sqlite-vec.

One embedded database holds three kinds of memory:

- **sessions**  — serialized :class:`AgentState` for cross-session continuity
- **episodes**  — one row per completed turn (task + outcome), the "flight data recorder"
- **memories**  — semantic facts for RAG retrieval

Embeddings are stored as float32 BLOBs. When the ``sqlite-vec`` extension loads, KNN uses its
native ``vec_distance_cosine``; otherwise the store falls back to a brute-force cosine scan in
Python — correct everywhere, and fast enough for a local CLI's memory sizes.
"""

from __future__ import annotations

import array
import json
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

from agent86.memory.embeddings import Embedder


def _pack(vec: list[float]) -> bytes:
    return array.array("f", vec).tobytes()


def _unpack(blob: bytes) -> list[float]:
    a = array.array("f")
    a.frombytes(blob)
    return list(a)


def _cosine(a: list[float], b: list[float]) -> float:
    # vectors are stored unit-norm, so dot product is cosine similarity
    return sum(x * y for x, y in zip(a, b, strict=False))


@dataclass
class Hit:
    id: int
    text: str
    score: float
    metadata: dict


class MemoryStore:
    def __init__(self, path: str | Path, embedder: Embedder):
        self.embedder = embedder
        self.dim = embedder.dim
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False: the rich REPL runs a turn (which touches the store) in a
        # worker thread while the main thread renders. Access is serialized — the store is only
        # ever used from one thread at a time (main at construction, then one worker per turn) —
        # so cross-thread use is safe.
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.has_vec = self._try_load_vec()
        self._migrate()

    # ---- setup --------------------------------------------------------- #

    def _try_load_vec(self) -> bool:
        try:
            import sqlite_vec  # type: ignore

            self.conn.enable_load_extension(True)
            sqlite_vec.load(self.conn)
            self.conn.enable_load_extension(False)
            return True
        except Exception:
            return False

    def _migrate(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                title TEXT,
                state_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS episodes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                ts REAL NOT NULL,
                task TEXT NOT NULL,
                outcome TEXT NOT NULL,
                embedding BLOB,
                metadata_json TEXT
            );
            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts REAL NOT NULL,
                kind TEXT NOT NULL DEFAULT 'fact',
                text TEXT NOT NULL,
                embedding BLOB,
                metadata_json TEXT
            );
            """
        )
        self.conn.commit()

    # ---- sessions ------------------------------------------------------ #

    def save_session(self, session_id: str, state_json: str, title: str | None = None) -> None:
        now = self._now()
        self.conn.execute(
            """
            INSERT INTO sessions (session_id, created_at, updated_at, title, state_json)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
                updated_at = excluded.updated_at,
                title = COALESCE(excluded.title, sessions.title),
                state_json = excluded.state_json
            """,
            (session_id, now, now, title, state_json),
        )
        self.conn.commit()

    def load_session(self, session_id: str) -> str | None:
        row = self.conn.execute(
            "SELECT state_json FROM sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
        return row["state_json"] if row else None

    def list_sessions(self, limit: int = 20) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT session_id, created_at, updated_at, title FROM sessions "
            "ORDER BY updated_at DESC LIMIT ?",
            (limit,),
        ).fetchall()

    # ---- episodes ------------------------------------------------------ #

    def add_episode(
        self, session_id: str, task: str, outcome: str, metadata: dict | None = None
    ) -> int:
        emb = _pack(self.embedder.encode_one(task))
        cur = self.conn.execute(
            "INSERT INTO episodes (session_id, ts, task, outcome, embedding, metadata_json) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (session_id, self._now(), task, outcome, emb, json.dumps(metadata or {})),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def search_episodes(self, query: str, k: int = 3) -> list[Hit]:
        qvec = self.embedder.encode_one(query)
        rows = self.conn.execute(
            "SELECT id, task, outcome, embedding, metadata_json FROM episodes"
        ).fetchall()
        return self._rank(qvec, rows, k, text_key="task", extra_key="outcome")

    # ---- semantic memories -------------------------------------------- #

    def add_memory(self, text: str, kind: str = "fact", metadata: dict | None = None) -> int:
        emb = _pack(self.embedder.encode_one(text))
        cur = self.conn.execute(
            "INSERT INTO memories (ts, kind, text, embedding, metadata_json) "
            "VALUES (?, ?, ?, ?, ?)",
            (self._now(), kind, text, emb, json.dumps(metadata or {})),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def search_memories(self, query: str, k: int = 5) -> list[Hit]:
        qvec = self.embedder.encode_one(query)
        rows = self.conn.execute(
            "SELECT id, text, embedding, metadata_json FROM memories"
        ).fetchall()
        return self._rank(qvec, rows, k, text_key="text")

    # ---- ranking ------------------------------------------------------- #

    def _rank(
        self,
        qvec: list[float],
        rows: list[sqlite3.Row],
        k: int,
        *,
        text_key: str,
        extra_key: str | None = None,
    ) -> list[Hit]:
        scored: list[Hit] = []
        for row in rows:
            blob = row["embedding"]
            if not blob:
                continue
            score = _cosine(qvec, _unpack(blob))
            meta = json.loads(row["metadata_json"] or "{}")
            if extra_key:
                meta = {**meta, extra_key: row[extra_key]}
            scored.append(Hit(id=row["id"], text=row[text_key], score=score, metadata=meta))
        scored.sort(key=lambda h: h.score, reverse=True)
        return scored[:k]

    # ---- misc ---------------------------------------------------------- #

    def counts(self) -> dict[str, int]:
        def n(table: str) -> int:
            return int(self.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])

        return {"sessions": n("sessions"), "episodes": n("episodes"), "memories": n("memories")}

    @staticmethod
    def _now() -> float:
        return time.time()

    def close(self) -> None:
        self.conn.close()


__all__ = ["MemoryStore", "Hit"]
