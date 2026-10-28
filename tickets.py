"""Ticket management: SQLite-backed store plus duplicate detection.

A ticket is created for a classified request only when no similar open
ticket (same category and domain) already exists; otherwise the report is
attached to the existing ticket.
"""
import json
import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import agent2

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DB_PATH = BASE_DIR / "data" / "tickets.db"

PREFIXES = {"incident": "INC", "change": "CHG", "problem": "PRB"}
STATUSES = ("open", "in_progress", "resolved", "closed")
OPEN_STATUSES = ("open", "in_progress")
TRANSITIONS = {
    "open": {"in_progress", "resolved", "closed"},
    "in_progress": {"open", "resolved", "closed"},
    "resolved": {"open", "closed"},  # reopen or close
    "closed": set(),
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS tickets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    number TEXT NOT NULL UNIQUE,
    category TEXT NOT NULL,
    seq INTEGER NOT NULL,
    domain TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    request TEXT NOT NULL DEFAULT '',
    priority TEXT,
    status TEXT NOT NULL DEFAULT 'open',
    assignee TEXT,
    resolution TEXT,
    payload TEXT NOT NULL DEFAULT '{}',
    occurrences INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (category, seq)
);
CREATE TABLE IF NOT EXISTS ticket_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id INTEGER NOT NULL REFERENCES tickets(id),
    kind TEXT NOT NULL,
    message TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tickets_lookup
    ON tickets (category, domain, status);
"""


class TicketError(Exception):
    """Base class for ticket errors."""


class TicketNotFound(TicketError):
    pass


class InvalidUpdate(TicketError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def duplicate_threshold() -> float:
    return float(os.getenv("TICKET_DUP_THRESHOLD", "0.80"))


class TicketStore:
    def __init__(self, path: str | os.PathLike | None = None) -> None:
        self.path = Path(
            path or os.getenv("TICKETS_DB") or DEFAULT_DB_PATH
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Serializes find-then-create inside this process; BEGIN IMMEDIATE
        # protects the numbering across processes.
        self.lock = threading.Lock()

        with self._connect() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(
            self.path, timeout=10, isolation_level=None
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
        finally:
            conn.close()

    @staticmethod
    def _to_dict(row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["payload"] = json.loads(item.get("payload") or "{}")
        item.pop("seq", None)
        return item

    @staticmethod
    def _event(conn, ticket_id: int, kind: str, message: str) -> None:
        conn.execute(
            "INSERT INTO ticket_events (ticket_id, kind, message, created_at)"
            " VALUES (?, ?, ?, ?)",
            (ticket_id, kind, message, _now()),
        )

    # ------------------------------------------------------------------
    # Create / read
    # ------------------------------------------------------------------

    def create(
        self,
        category: str,
        domain: str,
        title: str,
        description: str,
        request: str = "",
        priority: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        category = agent2.normalize_category(category)
        domain = agent2.normalize_domain(domain)
        now = _now()

        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                seq = conn.execute(
                    "SELECT COALESCE(MAX(seq), 0) + 1 FROM tickets"
                    " WHERE category = ?",
                    (category,),
                ).fetchone()[0]
                number = f"{PREFIXES[category]}{seq:07d}"

                cursor = conn.execute(
                    "INSERT INTO tickets (number, category, seq, domain,"
                    " title, description, request, priority, payload,"
                    " created_at, updated_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        number, category, seq, domain, title.strip(),
                        description.strip(), request.strip(), priority,
                        json.dumps(payload or {}, ensure_ascii=False),
                        now, now,
                    ),
                )
                assert cursor.lastrowid is not None
                self._event(
                    conn, cursor.lastrowid, "created",
                    f"Ticket {number} created.",
                )
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise

        return self.get(number)  # type: ignore[return-value]

    def get(self, number: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM tickets WHERE number = ?",
                (number.strip().upper(),),
            ).fetchone()

            if row is None:
                return None

            ticket = self._to_dict(row)
            events = conn.execute(
                "SELECT kind, message, created_at FROM ticket_events"
                " WHERE ticket_id = ? ORDER BY id",
                (row["id"],),
            ).fetchall()
            ticket["events"] = [dict(event) for event in events]
            return ticket

    def list_tickets(
        self,
        status: str | None = None,
        category: str | None = None,
        domain: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        clauses, params = [], []

        if status:
            if status not in STATUSES:
                raise InvalidUpdate(
                    f"status must be one of {', '.join(STATUSES)}"
                )
            clauses.append("status = ?")
            params.append(status)

        if category:
            clauses.append("category = ?")
            params.append(agent2.normalize_category(category))

        if domain:
            clauses.append("domain = ?")
            params.append(agent2.normalize_domain(domain))

        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""

        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM tickets{where} ORDER BY id DESC LIMIT ?",
                (*params, max(1, min(limit, 500))),
            ).fetchall()

        return [self._to_dict(row) for row in rows]

    def open_candidates(
        self, category: str, domain: str
    ) -> list[dict[str, Any]]:
        placeholders = ",".join("?" for _ in OPEN_STATUSES)

        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM tickets WHERE category = ? AND domain = ?"
                f" AND status IN ({placeholders})",
                (
                    agent2.normalize_category(category),
                    agent2.normalize_domain(domain),
                    *OPEN_STATUSES,
                ),
            ).fetchall()

        return [self._to_dict(row) for row in rows]

    # ------------------------------------------------------------------
    # Update
    # ------------------------------------------------------------------

    def add_duplicate_report(
        self, number: str, request: str
    ) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id FROM tickets WHERE number = ?", (number,)
            ).fetchone()

            if row is None:
                raise TicketNotFound(f"Ticket {number} not found.")

            conn.execute(
                "UPDATE tickets SET occurrences = occurrences + 1,"
                " updated_at = ? WHERE id = ?",
                (_now(), row["id"]),
            )
            self._event(
                conn, row["id"], "duplicate_report",
                f"Another report received: {request.strip()[:500]}",
            )

        return self.get(number)  # type: ignore[return-value]

    def update(
        self,
        number: str,
        status: str | None = None,
        assignee: str | None = None,
        resolution: str | None = None,
        comment: str | None = None,
    ) -> dict[str, Any]:
        number = number.strip().upper()

        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                row = conn.execute(
                    "SELECT * FROM tickets WHERE number = ?", (number,)
                ).fetchone()

                if row is None:
                    raise TicketNotFound(f"Ticket {number} not found.")

                updates: dict[str, Any] = {}
                events: list[tuple[str, str]] = []

                if status is not None and status != row["status"]:
                    if status not in STATUSES:
                        raise InvalidUpdate(
                            f"status must be one of {', '.join(STATUSES)}"
                        )
                    if status not in TRANSITIONS[row["status"]]:
                        raise InvalidUpdate(
                            f"Cannot move a {row['status']} ticket "
                            f"to {status}."
                        )
                    if status == "resolved" and not (
                        resolution or row["resolution"]
                    ):
                        raise InvalidUpdate(
                            "A resolution is required to resolve a ticket."
                        )
                    updates["status"] = status
                    events.append((
                        "status_change",
                        f"Status changed from {row['status']} to {status}.",
                    ))

                if assignee is not None and assignee != row["assignee"]:
                    updates["assignee"] = assignee.strip() or None
                    events.append(
                        ("assigned", f"Assigned to {assignee.strip() or 'nobody'}.")
                    )

                if resolution is not None:
                    updates["resolution"] = resolution.strip() or None
                    events.append(("resolution", "Resolution updated."))

                if comment and comment.strip():
                    events.append(("comment", comment.strip()))

                if updates:
                    updates["updated_at"] = _now()
                    assignments = ", ".join(f"{key} = ?" for key in updates)
                    conn.execute(
                        f"UPDATE tickets SET {assignments} WHERE id = ?",
                        (*updates.values(), row["id"]),
                    )
                elif events:
                    conn.execute(
                        "UPDATE tickets SET updated_at = ? WHERE id = ?",
                        (_now(), row["id"]),
                    )

                for kind, message in events:
                    self._event(conn, row["id"], kind, message)

                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise

        return self.get(number)  # type: ignore[return-value]


# ----------------------------------------------------------------------
# Duplicate detection
# ----------------------------------------------------------------------

def _texts(title: str, description: str, request: str) -> list[str]:
    texts = [f"{title}. {description}".strip(". "), request]
    return [text for text in dict.fromkeys(texts) if text.strip()]


def find_duplicate(
    candidates: list[dict[str, Any]],
    title: str,
    description: str,
    request: str,
    model,
) -> tuple[dict[str, Any] | None, float]:
    """Return (best matching open ticket or None, its score).

    Score = 0.7 * semantic + 0.3 * keyword, the same hybrid used for
    knowledge retrieval. An identical normalized request is always a
    duplicate. The threshold is TICKET_DUP_THRESHOLD (default 0.80).
    """
    if not candidates:
        return None, 0.0

    query_texts = _texts(title, description, request)
    if not query_texts:
        return None, 0.0

    normalized_request = agent2.normalize_text(request)
    best, best_score = None, 0.0

    from sklearn.metrics.pairwise import cosine_similarity

    candidate_texts = [
        _texts(c["title"], c["description"], c.get("request", ""))
        for c in candidates
    ]
    flat = [text for texts in candidate_texts for text in texts]

    query_vectors = model.encode(
        query_texts, normalize_embeddings=True, convert_to_numpy=True,
        show_progress_bar=False,
    )
    flat_vectors = model.encode(
        flat, normalize_embeddings=True, convert_to_numpy=True,
        show_progress_bar=False,
    )
    similarity = cosine_similarity(query_vectors, flat_vectors)

    offset = 0
    for candidate, texts in zip(candidates, candidate_texts):
        semantic = float(similarity[:, offset:offset + len(texts)].max())
        offset += len(texts)

        lexical_article = {
            "title": candidate["title"],
            "description": (
                f"{candidate['description']} {candidate.get('request', '')}"
            ),
            "resolution": "",
        }
        lexical = max(
            agent2.keyword_score(text, lexical_article)
            for text in query_texts
        )

        score = 0.7 * semantic + 0.3 * lexical

        if (
            normalized_request
            and normalized_request
            == agent2.normalize_text(candidate.get("request", ""))
        ):
            score = 1.0

        if score > best_score:
            best, best_score = candidate, score

    if best is not None and best_score >= duplicate_threshold():
        return best, round(best_score, 3)

    return None, round(best_score, 3)


def find_or_create(
    store: TicketStore,
    model,
    category: str,
    domain: str,
    title: str,
    description: str,
    request: str = "",
    priority: str | None = None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Attach to a matching open ticket, or create a new one."""
    with store.lock:
        duplicate, score = find_duplicate(
            store.open_candidates(category, domain),
            title, description, request, model,
        )

        if duplicate is not None:
            ticket = store.add_duplicate_report(
                duplicate["number"], request or description
            )
            return {
                "created": False,
                "duplicate_of": ticket["number"],
                "similarity": score,
                "ticket": ticket,
            }

        ticket = store.create(
            category, domain, title, description,
            request=request, priority=priority, payload=payload,
        )
        return {
            "created": True,
            "duplicate_of": None,
            "similarity": score,
            "ticket": ticket,
        }
