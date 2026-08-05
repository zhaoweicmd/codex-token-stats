from __future__ import annotations

import json
import os
import re
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import quote

from . import db
from .config import Config
from .models import ProjectInfo, TaskData, TurnUsage
from .projects import ProjectResolver

SESSION_ID_RE = re.compile(
    r"rollout-.*-([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\.jsonl"
)


def default_codex_home() -> Path:
    env = os.environ.get("CODEX_HOME")
    if env:
        return Path(env)
    return Path.home() / ".codex"


def parse_ts(value) -> Optional[int]:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        return int(dt.timestamp())
    return int(dt.timestamp())


def discover_files(codex_home: Path) -> List[Path]:
    found = set()
    for base in ("sessions", "archived_sessions"):
        folder = codex_home / base
        if folder.is_dir():
            for path in folder.rglob("*.jsonl"):
                try:
                    found.add(path.resolve())
                except OSError:
                    found.add(path)
    return sorted(found, key=lambda p: str(p).lower())


def load_session_index(codex_home: Path) -> Dict[str, dict]:
    index: Dict[str, dict] = {}
    path = codex_home / "session_index.jsonl"
    if not path.exists():
        return index
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if isinstance(rec, dict) and rec.get("id"):
                    index[str(rec["id"])] = rec
    except OSError:
        pass
    return index


def load_state_meta(codex_home: Path) -> Dict[str, dict]:
    states = sorted(
        codex_home.glob("state_*.sqlite"),
        key=lambda p: p.stat().st_mtime if p.exists() else 0,
        reverse=True,
    )
    if not states:
        return {}
    path = states[0]
    uri = "file:" + quote(str(path.resolve()), safe="/:") + "?mode=ro"
    meta: Dict[str, dict] = {}
    try:
        conn = sqlite3.connect(uri, uri=True)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT id, title, cwd, tokens_used, rollout_path, created_at,
                   updated_at, source, model_provider, model, git_origin_url,
                   git_branch, git_sha, name, first_user_message
            FROM threads
            """
        ).fetchall()
    except sqlite3.Error:
        return {}
    finally:
        try:
            conn.close()
        except Exception:
            pass
    for row in rows:
        meta[str(row["id"])] = {
            "title": row["title"] or "",
            "cwd": row["cwd"] or "",
            "tokens_used": int(row["tokens_used"] or 0),
            "rollout_path": row["rollout_path"] or "",
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "source": row["source"] or "",
            "model_provider": row["model_provider"] or "",
            "model": row["model"] or "",
            "git_origin_url": row["git_origin_url"] or "",
            "name": row["name"] or "",
            "first_user_message": row["first_user_message"] or "",
        }
    return meta


def _usage_delta(total: dict, previous: dict) -> dict:
    keys = (
        "input_tokens",
        "cached_input_tokens",
        "cache_write_input_tokens",
        "output_tokens",
        "reasoning_output_tokens",
        "total_tokens",
    )
    return {
        key: max(0, int(total.get(key, 0) or 0) - int(previous.get(key, 0) or 0))
        for key in keys
    }


def parse_session_file(
    path: Path,
    state_meta: Dict[str, dict],
    session_index: Dict[str, dict],
) -> Optional[TaskData]:
    task = TaskData(id="", rollout_path=str(path))
    first_user_message = ""
    last_ts: Optional[int] = None
    filename_match = SESSION_ID_RE.search(str(path))
    filename_id = filename_match.group(1) if filename_match else ""

    try:
        handle = path.open("r", encoding="utf-8")
    except OSError:
        return None
    with handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if not isinstance(rec, dict):
                continue
            ts = parse_ts(rec.get("timestamp"))
            if ts is not None:
                last_ts = ts
            rtype = rec.get("type")
            if rtype == "session_meta":
                payload = rec.get("payload") or {}
                if not task.id:
                    task.id = str(payload.get("id") or payload.get("session_id") or "")
                task.cwd = task.cwd or str(payload.get("cwd") or "")
                task.provider = task.provider or str(payload.get("model_provider") or "")
                source_value = payload.get("source")
                if isinstance(source_value, dict):
                    source_value = "subagent" if "subagent" in source_value else ""
                elif not isinstance(source_value, str):
                    source_value = ""
                task.source = task.source or source_value
                task.originator = task.originator or str(payload.get("originator") or "")
                task.cli_version = task.cli_version or str(payload.get("cli_version") or "")
                if task.created_at is None and ts is not None:
                    task.created_at = ts
                continue
            if rtype == "event_msg":
                payload = rec.get("payload") or {}
                ptype = payload.get("type")
                if ptype == "token_count":
                    info = payload.get("info") or {}
                    total = info.get("total_token_usage") or {}
                    last = info.get("last_token_usage")
                    usage = None
                    if isinstance(total, dict) and total:
                        previous = _last_cumulative(task.turns)
                        if total != previous:
                            usage = _usage_delta(total, previous)
                    elif isinstance(last, dict) and last:
                        usage = last
                    if isinstance(usage, dict):
                        if not any(usage.get(key, 0) for key in (
                            "input_tokens",
                            "output_tokens",
                            "reasoning_output_tokens",
                            "total_tokens",
                        )):
                            continue
                        task.turns.append(
                            TurnUsage(
                                ts=ts if ts is not None else (task.created_at or int(time.time())),
                                input_tokens=int(usage.get("input_tokens", 0) or 0),
                                cached_input_tokens=int(usage.get("cached_input_tokens", 0) or 0),
                                cache_write_input_tokens=int(usage.get("cache_write_input_tokens", 0) or 0),
                                output_tokens=int(usage.get("output_tokens", 0) or 0),
                                reasoning_output_tokens=int(usage.get("reasoning_output_tokens", 0) or 0),
                                total_tokens=int(usage.get("total_tokens", 0) or 0),
                            )
                        )
                elif ptype == "user_message":
                    msg = payload.get("message")
                    if isinstance(msg, str) and msg.strip() and not first_user_message:
                        first_user_message = msg.strip()[:120]

    if filename_id:
        task.id = filename_id
    if not task.id:
        return None

    meta = state_meta.get(task.id)
    if meta:
        task.cwd = task.cwd or meta["cwd"]
        task.provider = task.provider or meta["model_provider"]
        task.model = task.model or meta["model"]
        task.source = task.source or meta["source"]
        task.git_url = task.git_url or meta["git_origin_url"]
        if meta["created_at"] and task.created_at is None:
            task.created_at = int(meta["created_at"])
        if meta["updated_at"] and task.updated_at is None:
            task.updated_at = int(meta["updated_at"])
        if not task.title:
            task.title = meta["title"] or meta["name"] or meta["first_user_message"]

    index = session_index.get(task.id)
    if index:
        task.title = str(index.get("thread_name") or task.title)
        if task.updated_at is None:
            task.updated_at = parse_ts(index.get("updated_at"))

    if not task.title:
        task.title = first_user_message or "未命名任务"
    task.title = (task.title or "未命名任务").strip()[:200] or "未命名任务"
    if "subagent" in task.source:
        task.source = "subagent"
    if task.created_at is None:
        try:
            task.created_at = int(path.stat().st_mtime)
        except OSError:
            task.created_at = int(time.time())
    if task.updated_at is None:
        task.updated_at = last_ts or task.created_at

    if not task.turns and meta and meta["tokens_used"]:
        task.usage_source = "state_fallback"
        task.fallback_total = meta["tokens_used"]
        task.turns.append(
            TurnUsage(ts=task.created_at, total_tokens=meta["tokens_used"])
        )

    task.status = "archived" if "archived_sessions" in path.parts else "active"
    return task


def _last_cumulative(turns: List[TurnUsage]) -> dict:
    return {
        "input_tokens": sum(t.input_tokens for t in turns),
        "cached_input_tokens": sum(t.cached_input_tokens for t in turns),
        "cache_write_input_tokens": sum(t.cache_write_input_tokens for t in turns),
        "output_tokens": sum(t.output_tokens for t in turns),
        "reasoning_output_tokens": sum(t.reasoning_output_tokens for t in turns),
        "total_tokens": sum(t.total_tokens for t in turns),
    }


def scan(
    conn: sqlite3.Connection,
    codex_home: Optional[Path] = None,
    config: Optional[Config] = None,
) -> dict:
    config = config or Config()
    home = Path(codex_home or config.codex_home or default_codex_home())
    db.init_db(conn)
    resolver = ProjectResolver(config)
    session_index = load_session_index(home)
    state_meta = load_state_meta(home)
    files = discover_files(home)
    overrides = {
        row["task_id"]: row["project_name"]
        for row in db.all_project_overrides(conn)
    }

    def project_for(task: TaskData) -> ProjectInfo:
        override_name = overrides.get(task.id)
        if override_name:
            return ProjectInfo(
                key=f"override:{override_name}",
                name=override_name,
                kind="override",
                path=task.cwd,
            )
        return resolver.resolve(task.cwd, task.git_url, task.title)

    scanned = 0
    skipped = 0
    failed = 0
    meta_refreshed = 0
    for path in files:
        try:
            stat = path.stat()
        except OSError:
            failed += 1
            continue
        state = db.get_scan_state(conn, str(path))
        if state is not None and int(state["size"]) == stat.st_size and abs(float(state["mtime"]) - stat.st_mtime) < 0.01:
            skipped += 1
            continue
        task = parse_session_file(path, state_meta, session_index)
        if task is None:
            failed += 1
            continue
        project = project_for(task)
        task.project = project
        project_id = db.upsert_project(conn, project)
        db.upsert_task(conn, task, project_id)
        db.replace_turns(conn, task.id, task.turns)
        db.set_scan_state(conn, str(path), stat.st_size, stat.st_mtime)
        conn.commit()
        scanned += 1

    rows = conn.execute("SELECT id, cwd, title FROM tasks").fetchall()
    for row in rows:
        meta = state_meta.get(str(row["id"]), {})
        override_name = overrides.get(str(row["id"]))
        if override_name:
            project = ProjectInfo(
                key=f"override:{override_name}",
                name=override_name,
                kind="override",
                path=str(row["cwd"] or ""),
            )
        else:
            project = resolver.resolve(
                str(row["cwd"] or ""),
                str(meta.get("git_origin_url") or ""),
                str(row["title"] or ""),
            )
        project_id = db.upsert_project(conn, project)
        conn.execute(
            "UPDATE tasks SET project_id = ? WHERE id = ?",
            (project_id, str(row["id"])),
        )
        meta_refreshed += 1
    conn.commit()

    return {
        "codex_home": str(home),
        "files": len(files),
        "scanned": scanned,
        "skipped": skipped,
        "failed": failed,
        "meta_refreshed": meta_refreshed,
    }
