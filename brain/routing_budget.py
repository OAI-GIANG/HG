"""Durable SQLite routing-budget counter with atomic reservations.

This is a real persistence component, not a production binding by itself. Production
must choose a protected database path, bind reservations to trusted task/candidate/
policy identity, and verify lifecycle/backup policy before enabling it.
"""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import sqlite3
import threading
from typing import Any


class RoutingBudgetError(RuntimeError):
    pass


class SQLiteRoutingBudgetLedger:
    """Persist per-task call counts; reserve() atomically enforces the supplied limit."""

    _CATEGORIES = {"reasoning", "revision", "council"}

    def __init__(self, path: str | Path, *, timeout: float = 5.0):
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout <= 0:
            raise ValueError("timeout must be positive")
        self.path = Path(path)
        self.timeout = float(timeout)
        self._lock = threading.RLock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=FULL")
            connection.execute("""
                CREATE TABLE IF NOT EXISTS routing_budget_usage (
                    task_ref TEXT NOT NULL,
                    category TEXT NOT NULL CHECK(category IN ('reasoning','revision','council')),
                    used INTEGER NOT NULL CHECK(used >= 0),
                    PRIMARY KEY(task_ref, category)
                )
            """)
            connection.execute("""
                CREATE TABLE IF NOT EXISTS routing_budget_reservations (
                    call_id TEXT PRIMARY KEY,
                    task_ref TEXT NOT NULL,
                    candidate_ref TEXT NOT NULL,
                    policy_version TEXT NOT NULL,
                    route TEXT NOT NULL,
                    category TEXT NOT NULL CHECK(category IN ('reasoning','revision','council')),
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)

    @contextmanager
    def _connection(self):
        connection = sqlite3.connect(self.path, timeout=self.timeout, isolation_level=None)
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA busy_timeout = " + str(int(self.timeout * 1000)))
            yield connection
        finally:
            connection.close()

    @staticmethod
    def _validate_task(task_ref):
        if not isinstance(task_ref, str) or not task_ref.strip():
            raise RoutingBudgetError("task_ref is required")

    @classmethod
    def _validate_category(cls, category):
        if category not in cls._CATEGORIES:
            raise RoutingBudgetError("unknown routing budget category")

    @staticmethod
    def _validate_limit(limit):
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 0:
            raise RoutingBudgetError("limit must be a non-negative integer")

    def get_usage(self, task_ref: str) -> dict[str, int]:
        self._validate_task(task_ref)
        try:
            with self._connection() as connection:
                rows = connection.execute(
                    "SELECT category, used FROM routing_budget_usage WHERE task_ref=?",
                    (task_ref,),
                ).fetchall()
            result = {name: 0 for name in self._CATEGORIES}
            result.update({row["category"]: row["used"] for row in rows})
            return result
        except sqlite3.Error as exc:
            raise RoutingBudgetError("durable budget read failed") from exc


    @staticmethod
    def _required_binding(name: str, value: Any) -> str:
        if not isinstance(value, str) or not value.strip():
            raise RoutingBudgetError(name + " is required for identity-bound reservation")
        return value.strip()

    def reserve_bound(self, *, task_ref: str, candidate_ref: str, policy_version: str,
                      route: str, category: str, call_id: str, limit: int) -> bool:
        """Atomically reserve a uniquely identified call under immutable task bindings.

        The caller must derive these bindings from trusted runtime state, never model
        output or Memory text. A call_id is single-use, including across restarts.
        Legacy reserve() remains available for compatibility but is not sufficient
        evidence for a router-enabled production call.
        """
        self._validate_task(task_ref)
        candidate_ref = self._required_binding("candidate_ref", candidate_ref)
        policy_version = self._required_binding("policy_version", policy_version)
        route = self._required_binding("route", route)
        call_id = self._required_binding("call_id", call_id)
        self._validate_category(category)
        self._validate_limit(limit)
        try:
            with self._lock, self._connection() as connection:
                connection.execute("BEGIN IMMEDIATE")
                existing = connection.execute(
                    "SELECT task_ref,candidate_ref,policy_version,route,category "
                    "FROM routing_budget_reservations WHERE call_id=?", (call_id,)
                ).fetchone()
                if existing is not None:
                    connection.execute("ROLLBACK")
                    return False
                row = connection.execute(
                    "SELECT used FROM routing_budget_usage WHERE task_ref=? AND category=?",
                    (task_ref, category),
                ).fetchone()
                used = 0 if row is None else row["used"]
                if used >= limit:
                    connection.execute("ROLLBACK")
                    return False
                if row is None:
                    connection.execute(
                        "INSERT INTO routing_budget_usage(task_ref,category,used) VALUES(?,?,1)",
                        (task_ref, category),
                    )
                else:
                    connection.execute(
                        "UPDATE routing_budget_usage SET used=? WHERE task_ref=? AND category=? AND used=?",
                        (used + 1, task_ref, category, used),
                    )
                    if connection.execute("SELECT changes()").fetchone()[0] != 1:
                        connection.execute("ROLLBACK")
                        return False
                connection.execute(
                    "INSERT INTO routing_budget_reservations"
                    "(call_id,task_ref,candidate_ref,policy_version,route,category) VALUES(?,?,?,?,?,?)",
                    (call_id, task_ref, candidate_ref, policy_version, route, category),
                )
                connection.execute("COMMIT")
                return True
        except sqlite3.Error as exc:
            raise RoutingBudgetError("identity-bound budget reservation failed closed") from exc

    def reserve(self, task_ref: str, category: str, limit: int) -> bool:
        """Atomically increment one counter iff its current value is below limit."""
        self._validate_task(task_ref)
        self._validate_category(category)
        self._validate_limit(limit)
        try:
            with self._lock, self._connection() as connection:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    "SELECT used FROM routing_budget_usage WHERE task_ref=? AND category=?",
                    (task_ref, category),
                ).fetchone()
                used = 0 if row is None else row["used"]
                if used >= limit:
                    connection.execute("ROLLBACK")
                    return False
                if row is None:
                    connection.execute(
                        "INSERT INTO routing_budget_usage(task_ref, category, used) VALUES (?, ?, 1)",
                        (task_ref, category),
                    )
                else:
                    connection.execute(
                        "UPDATE routing_budget_usage SET used=? WHERE task_ref=? AND category=? AND used=?",
                        (used + 1, task_ref, category, used),
                    )
                    if connection.execute("SELECT changes()").fetchone()[0] != 1:
                        connection.execute("ROLLBACK")
                        return False
                connection.execute("COMMIT")
                return True
        except sqlite3.Error as exc:
            raise RoutingBudgetError("durable budget reservation failed closed") from exc
