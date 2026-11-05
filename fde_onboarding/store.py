"""SQLite store. Reopening the same file resumes identically."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path


class Store:
    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self._init_schema()

    def _init_schema(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS tenants (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                created_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS step_progress (
                tenant_id TEXT NOT NULL,
                step_id TEXT NOT NULL,
                state TEXT NOT NULL,
                started_at REAL,
                completed_at REAL,
                error TEXT,
                payload_json TEXT,
                PRIMARY KEY (tenant_id, step_id)
            );
            """
        )
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    # tenants -------------------------------------------------------
    def create_tenant(self, tenant_id: str, name: str, created_at: float, step_rows: list[tuple[str, str]]) -> dict:
        self.conn.execute(
            "INSERT INTO tenants (id, name, created_at) VALUES (?, ?, ?)",
            (tenant_id, name, created_at),
        )
        self.conn.executemany(
            "INSERT INTO step_progress (tenant_id, step_id, state) VALUES (?, ?, ?)",
            [(tenant_id, sid, state) for sid, state in step_rows],
        )
        self.conn.commit()
        return self.get_tenant(tenant_id)

    def get_tenant(self, tenant_id: str) -> dict | None:
        row = self.conn.execute("SELECT * FROM tenants WHERE id=?", (tenant_id,)).fetchone()
        return dict(row) if row else None

    def list_tenants(self) -> list[dict]:
        return [dict(r) for r in self.conn.execute("SELECT * FROM tenants ORDER BY id")]

    # steps ---------------------------------------------------------
    def get_step(self, tenant_id: str, step_id: str) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM step_progress WHERE tenant_id=? AND step_id=?", (tenant_id, step_id)
        ).fetchone()
        return dict(row) if row else None

    def list_steps(self, tenant_id: str) -> list[dict]:
        return [
            dict(r)
            for r in self.conn.execute(
                "SELECT * FROM step_progress WHERE tenant_id=?", (tenant_id,)
            )
        ]

    def update_step(self, tenant_id: str, step_id: str, **fields) -> None:
        if not fields:
            return
        cols = ", ".join(f"{k}=?" for k in fields)
        self.conn.execute(
            f"UPDATE step_progress SET {cols} WHERE tenant_id=? AND step_id=?",
            (*fields.values(), tenant_id, step_id),
        )
        self.conn.commit()
