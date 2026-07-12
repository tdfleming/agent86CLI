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
            vec = _unpack(blob)
            if len(vec) != len(qvec):
                # Row was embedded by a different embedder (dimension changed); skip it
                # rather than compute a meaningless cross-dimension similarity.
                continue
            score = _cosine(qvec, vec)
            meta = json.loads(row["metadata_json"] or "{}")
            if extra_key:
                meta = {**meta, extra_key: row[extra_key]}
            scored.append(Hit(id=row["id"], text=row[text_key], score=score, metadata=meta))
        scored.sort(key=lambda h: h.score, reverse=True)
        return scored[:k]

    # ---- pruning ------------------------------------------------------- #

    def delete_memory(self, mem_id: int) -> bool:
        """Delete a single semantic memory by id. Returns True if a row was removed."""
        cur = self.conn.execute("DELETE FROM memories WHERE id = ?", (mem_id,))
        self.conn.commit()
        return cur.rowcount > 0

    def _prune_table(
        self,
        table: str,
        ts_col: str,
        id_col: str,
        *,
        older_than_days: float | None,
        keep_last: int | None,
    ) -> int:
        """Delete rows failing any given retention constraint; return the count removed.

        A row survives only if it is newer than the age cutoff AND among the ``keep_last``
        most recent. Constraints left as ``None`` are not applied.
        """
        deleted = 0
        if older_than_days is not None:
            cutoff = self._now() - older_than_days * 86400.0
            cur = self.conn.execute(
                f"DELETE FROM {table} WHERE {ts_col} < ?", (cutoff,)  # noqa: S608 (fixed idents)
            )
            deleted += cur.rowcount
        if keep_last is not None:
            cur = self.conn.execute(
                f"DELETE FROM {table} WHERE {id_col} NOT IN "  # noqa: S608 (fixed idents)
                f"(SELECT {id_col} FROM {table} ORDER BY {ts_col} DESC LIMIT ?)",
                (max(0, keep_last),),
            )
            deleted += cur.rowcount
        self.conn.commit()
        return deleted

    def prune(
        self,
        *,
        older_than_days: float | None = None,
        keep_last: int | None = None,
        episodes: bool = True,
        sessions: bool = True,
        memories: bool = False,
    ) -> dict[str, int]:
        """Apply retention limits to the log tables. Returns rows deleted per table.

        Episodes and sessions (the append-only flight recorder) are pruned by default;
        curated semantic ``memories`` are only touched when explicitly requested.
        """
        removed: dict[str, int] = {}
        if episodes:
            removed["episodes"] = self._prune_table(
                "episodes", "ts", "id", older_than_days=older_than_days, keep_last=keep_last
            )
        if sessions:
            removed["sessions"] = self._prune_table(
                "sessions", "updated_at", "session_id",
                older_than_days=older_than_days, keep_last=keep_last,
            )
        if memories:
            removed["memories"] = self._prune_table(
                "memories", "ts", "id", older_than_days=older_than_days, keep_last=keep_last
            )
        return removed

    def enforce_retention(
        self,
        *,
        max_episodes: int = 0,
        max_sessions: int = 0,
        max_age_days: float = 0.0,
    ) -> dict[str, int]:
        """Apply per-table retention caps to the log. A cap of 0 disables it.

        Unlike :meth:`prune`, each table gets its own count cap. Curated semantic memories
        are never touched. Returns rows deleted per table (only for tables that were capped).
        """
        age = max_age_days or None
        removed: dict[str, int] = {}
        if max_episodes or age:
            n = self._prune_table(
                "episodes", "ts", "id",
                older_than_days=age, keep_last=(max_episodes or None),
            )
            if n:
                removed["episodes"] = n
        if max_sessions or age:
            n = self._prune_table(
                "sessions", "updated_at", "session_id",
                older_than_days=age, keep_last=(max_sessions or None),
            )
            if n:
                removed["sessions"] = n
        return removed

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
