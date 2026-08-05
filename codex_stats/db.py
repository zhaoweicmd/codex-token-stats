from __future__ import annotations

import sqlite3
import time
from typing import Optional

from .models import ProjectInfo, TaskData

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'cwd',
    path TEXT NOT NULL DEFAULT '',
    git_url TEXT NOT NULL DEFAULT '',
    first_seen_at INTEGER NOT NULL DEFAULT 0,
    last_seen_at INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL DEFAULT '',
    cwd TEXT NOT NULL DEFAULT '',
    project_id INTEGER REFERENCES projects(id) ON DELETE SET NULL,
    provider TEXT NOT NULL DEFAULT '',
    model TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT '',
    originator TEXT NOT NULL DEFAULT '',
    cli_version TEXT NOT NULL DEFAULT '',
    created_at INTEGER,
    updated_at INTEGER,
    total_input_tokens INTEGER NOT NULL DEFAULT 0,
    total_cached_input_tokens INTEGER NOT NULL DEFAULT 0,
    total_cache_write_input_tokens INTEGER NOT NULL DEFAULT 0,
    total_output_tokens INTEGER NOT NULL DEFAULT 0,
    total_reasoning_output_tokens INTEGER NOT NULL DEFAULT 0,
    total_tokens INTEGER NOT NULL DEFAULT 0,
    turn_count INTEGER NOT NULL DEFAULT 0,
    usage_source TEXT NOT NULL DEFAULT 'jsonl',
    status TEXT NOT NULL DEFAULT 'active',
    rollout_path TEXT NOT NULL DEFAULT '',
    last_scanned_at INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_tasks_cwd ON tasks(cwd);
CREATE INDEX IF NOT EXISTS idx_tasks_project ON tasks(project_id);
CREATE INDEX IF NOT EXISTS idx_tasks_created ON tasks(created_at);
CREATE INDEX IF NOT EXISTS idx_tasks_provider ON tasks(provider);
CREATE INDEX IF NOT EXISTS idx_tasks_model ON tasks(model);

CREATE TABLE IF NOT EXISTS turns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    turn_index INTEGER NOT NULL,
    ts INTEGER NOT NULL,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    cached_input_tokens INTEGER NOT NULL DEFAULT 0,
    cache_write_input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    reasoning_output_tokens INTEGER NOT NULL DEFAULT 0,
    total_tokens INTEGER NOT NULL DEFAULT 0,
    UNIQUE(task_id, turn_index)
);

CREATE INDEX IF NOT EXISTS idx_turns_task_ts ON turns(task_id, ts);
CREATE INDEX IF NOT EXISTS idx_turns_ts ON turns(ts);

CREATE TABLE IF NOT EXISTS scan_state (
    path TEXT PRIMARY KEY,
    size INTEGER NOT NULL DEFAULT 0,
    mtime REAL NOT NULL DEFAULT 0,
    last_scanned_at INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS project_overrides (
    task_id TEXT PRIMARY KEY REFERENCES tasks(id) ON DELETE CASCADE,
    project_name TEXT NOT NULL,
    updated_at INTEGER NOT NULL DEFAULT 0
);
"""


def connect(path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


def upsert_project(conn: sqlite3.Connection, project: ProjectInfo) -> int:
    now = int(time.time())
    conn.execute(
        """
        INSERT INTO projects (key, name, kind, path, git_url, first_seen_at, last_seen_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET
            name = excluded.name,
            kind = excluded.kind,
            path = excluded.path,
            git_url = excluded.git_url,
            last_seen_at = excluded.last_seen_at
        """,
        (project.key, project.name, project.kind, project.path,
         project.git_url, now, now),
    )
    row = conn.execute("SELECT id FROM projects WHERE key = ?", (project.key,)).fetchone()
    return int(row["id"])


def upsert_task(conn: sqlite3.Connection, task: TaskData, project_id: Optional[int]) -> None:
    now = int(time.time())
    total_input = sum(t.input_tokens for t in task.turns)
    total_cached = sum(t.cached_input_tokens for t in task.turns)
    total_cache_write = sum(t.cache_write_input_tokens for t in task.turns)
    total_output = sum(t.output_tokens for t in task.turns)
    total_reasoning = sum(t.reasoning_output_tokens for t in task.turns)
    total = sum(t.total_tokens for t in task.turns)
    if total == 0 and task.fallback_total:
        total = task.fallback_total
    conn.execute(
        """
        INSERT INTO tasks (
            id, title, cwd, project_id, provider, model, source, originator,
            cli_version, created_at, updated_at, total_input_tokens,
            total_cached_input_tokens, total_cache_write_input_tokens,
            total_output_tokens, total_reasoning_output_tokens, total_tokens,
            turn_count, usage_source, status, rollout_path, last_scanned_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            title = excluded.title,
            cwd = excluded.cwd,
            project_id = excluded.project_id,
            provider = excluded.provider,
            model = excluded.model,
            source = excluded.source,
            originator = excluded.originator,
            cli_version = excluded.cli_version,
            created_at = COALESCE(excluded.created_at, tasks.created_at),
            updated_at = COALESCE(excluded.updated_at, tasks.updated_at),
            total_input_tokens = excluded.total_input_tokens,
            total_cached_input_tokens = excluded.total_cached_input_tokens,
            total_cache_write_input_tokens = excluded.total_cache_write_input_tokens,
            total_output_tokens = excluded.total_output_tokens,
            total_reasoning_output_tokens = excluded.total_reasoning_output_tokens,
            total_tokens = excluded.total_tokens,
            turn_count = excluded.turn_count,
            usage_source = excluded.usage_source,
            status = excluded.status,
            rollout_path = excluded.rollout_path,
            last_scanned_at = excluded.last_scanned_at
        """,
        (
            task.id, task.title, task.cwd, project_id, task.provider, task.model,
            task.source, task.originator, task.cli_version, task.created_at,
            task.updated_at, total_input, total_cached, total_cache_write,
            total_output, total_reasoning, total, len(task.turns),
            task.usage_source, task.status, task.rollout_path, now,
        ),
    )


def replace_turns(conn: sqlite3.Connection, task_id: str, turns) -> None:
    conn.execute("DELETE FROM turns WHERE task_id = ?", (task_id,))
    rows = [
        (
            task_id, index, t.ts, t.input_tokens, t.cached_input_tokens,
            t.cache_write_input_tokens, t.output_tokens,
            t.reasoning_output_tokens, t.total_tokens,
        )
        for index, t in enumerate(turns)
    ]
    conn.executemany(
        """
        INSERT INTO turns (
            task_id, turn_index, ts, input_tokens, cached_input_tokens,
            cache_write_input_tokens, output_tokens, reasoning_output_tokens,
            total_tokens
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )


def get_scan_state(conn: sqlite3.Connection, path: str):
    return conn.execute(
        "SELECT size, mtime FROM scan_state WHERE path = ?", (path,)
    ).fetchone()


def set_scan_state(conn: sqlite3.Connection, path: str, size: int, mtime: float) -> None:
    now = int(time.time())
    conn.execute(
        """
        INSERT INTO scan_state (path, size, mtime, last_scanned_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(path) DO UPDATE SET
            size = excluded.size,
            mtime = excluded.mtime,
            last_scanned_at = excluded.last_scanned_at
        """,
        (path, size, mtime, now),
    )


def get_project_override(conn: sqlite3.Connection, task_id: str) -> Optional[str]:
    row = conn.execute(
        "SELECT project_name FROM project_overrides WHERE task_id = ?",
        (task_id,),
    ).fetchone()
    return row["project_name"] if row else None


def set_project_override(conn: sqlite3.Connection, task_id: str, project_name: str) -> None:
    now = int(time.time())
    conn.execute(
        """
        INSERT INTO project_overrides (task_id, project_name, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(task_id) DO UPDATE SET
            project_name = excluded.project_name,
            updated_at = excluded.updated_at
        """,
        (task_id, project_name, now),
    )
    conn.commit()


def clear_project_override(conn: sqlite3.Connection, task_id: str) -> None:
    conn.execute("DELETE FROM project_overrides WHERE task_id = ?", (task_id,))
    conn.commit()


def all_project_overrides(conn: sqlite3.Connection):
    return conn.execute(
        "SELECT task_id, project_name FROM project_overrides"
    ).fetchall()
