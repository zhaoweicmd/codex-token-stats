from __future__ import annotations

import re
import sqlite3
from datetime import date, datetime, time, timedelta
from typing import Any, Dict, List, Optional, Tuple

from .pricing import cost_from_row, cost_sql, display_model

USAGE_COLUMNS = (
    "input_tokens",
    "cached_input_tokens",
    "cache_write_input_tokens",
    "output_tokens",
    "reasoning_output_tokens",
    "total_tokens",
)

UNPRICED_TASK_SQL = (
    "COUNT(DISTINCT CASE WHEN LOWER(COALESCE(t.model, '')) NOT IN "
    "('gpt-5.6-luna', 'gpt-5.6-sol', 'gpt-5.6-sol-g', '5.6 sol g', "
    "'gpt-5.6-terra', 'gpt-6-astra', "
    "'deepseek-v4-flash', 'deepseek-v4-flash-0731', 'deepseek-v4-pro', "
    "'deepseek-v4-pro-0813') THEN t.id END) AS unpriced_task_count"
)


def _parse_datetime(value: str) -> Optional[datetime]:
    text = (value or "").strip()
    if not text:
        return None
    for fmt in (
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
    ):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _is_date_only(value: str) -> bool:
    return bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", (value or "").strip()))


def _start_ts(day: date) -> int:
    return int(datetime.combine(day, time.min).timestamp())


def _end_exclusive(day: date) -> int:
    return _start_ts(day + timedelta(days=1))


def period_range(
    period: str = "all",
    from_str: str = "",
    to_str: str = "",
) -> Tuple[Optional[int], Optional[int]]:
    today = date.today()
    if from_str or to_str:
        start_dt = _parse_datetime(from_str) if from_str else datetime(1970, 1, 1)
        end_dt = _parse_datetime(to_str) if to_str else datetime.combine(today, time.max)
        if start_dt is None or end_dt is None:
            raise ValueError("时间格式应为 YYYY-MM-DD 或 YYYY-MM-DD HH:MM")
        start_ts = int(start_dt.timestamp())
        if to_str and _is_date_only(to_str):
            end_ts = _end_exclusive(end_dt.date())
        elif to_str:
            end_ts = int(end_dt.timestamp()) + 60
        else:
            end_ts = _end_exclusive(today)
        if start_ts > end_ts:
            raise ValueError("结束时间不能早于开始时间")
        return start_ts, end_ts

    if period in ("today", "day"):
        return _start_ts(today), _end_exclusive(today)
    if period == "yesterday":
        day = today - timedelta(days=1)
        return _start_ts(day), _end_exclusive(day)
    if period in ("7d", "7day"):
        return _start_ts(today - timedelta(days=6)), _end_exclusive(today)
    if period in ("30d", "30day"):
        return _start_ts(today - timedelta(days=29)), _end_exclusive(today)
    if period == "week":
        return _start_ts(today - timedelta(days=today.weekday())), _end_exclusive(today)
    if period == "month":
        return _start_ts(today.replace(day=1)), _end_exclusive(today)
    if period == "year":
        return _start_ts(today.replace(month=1, day=1)), _end_exclusive(today)
    return None, None


def period_label(start: Optional[int], end: Optional[int]) -> str:
    if start is None and end is None:
        return "全部时间"
    start_text = _format_boundary(start, False) if start else "最早"
    end_text = _format_boundary(end, True) if end else "至今"
    return f"{start_text} ~ {end_text}"


def _format_boundary(ts: Optional[int], is_end: bool) -> str:
    if ts is None:
        return "至今"
    if is_end:
        dt = datetime.fromtimestamp(ts - 1)
        if dt.hour == 23 and dt.minute == 59:
            return dt.strftime("%Y-%m-%d")
        return dt.strftime("%Y-%m-%d %H:%M")
    dt = datetime.fromtimestamp(ts)
    if dt.hour == 0 and dt.minute == 0:
        return dt.strftime("%Y-%m-%d")
    return dt.strftime("%Y-%m-%d %H:%M")


def _join(
    start: Optional[int],
    end: Optional[int],
    project_key: Optional[str] = None,
    provider: Optional[str] = None,
    query: str = "",
) -> Tuple[str, List[Any]]:
    conditions: List[str] = []
    params: List[Any] = []
    if start is not None:
        conditions.append("tr.ts >= ?")
        params.append(start)
    if end is not None:
        conditions.append("tr.ts < ?")
        params.append(end)
    if project_key:
        conditions.append("COALESCE(p.name, '未知') = ?")
        params.append(project_key)
    if provider:
        conditions.append("t.provider = ?")
        params.append(provider)
    query = (query or "").strip()
    if query:
        conditions.append("(t.title LIKE ? OR t.cwd LIKE ? OR p.name LIKE ?)")
        like = f"%{query}%"
        params.extend([like, like, like])
    base = (
        "FROM turns tr "
        "JOIN tasks t ON t.id = tr.task_id "
        "LEFT JOIN projects p ON p.id = t.project_id"
    )
    if conditions:
        base += " WHERE " + " AND ".join(conditions)
    return base, params


def summary(
    conn: sqlite3.Connection,
    start: Optional[int],
    end: Optional[int],
    project_key: Optional[str] = None,
    provider: Optional[str] = None,
) -> Dict[str, Any]:
    base, params = _join(start, end, project_key, provider)
    sums = ", ".join(
        f"COALESCE(SUM(tr.{column}), 0) AS {column}" for column in USAGE_COLUMNS
    )
    row = conn.execute(
        f"""
        SELECT COUNT(DISTINCT t.id) AS task_count,
               COUNT(tr.id) AS turn_count,
               {UNPRICED_TASK_SQL},
               {sums},
               {cost_sql()}
        {base}
        """,
        params,
    ).fetchone()
    return dict(row)


def _group_expression(dimension: str) -> Tuple[str, str]:
    if dimension == "project":
        return (
            "COALESCE(p.name, '未知') AS group_key, "
            "COALESCE(p.name, '未知') AS group_name",
            "COALESCE(p.name, '未知')",
        )
    if dimension == "provider":
        return (
            "COALESCE(NULLIF(t.provider, ''), '未知') AS group_key, "
            "COALESCE(NULLIF(t.provider, ''), '未知') AS group_name",
            "t.provider",
        )
    if dimension == "model":
        return (
            "COALESCE(NULLIF(t.model, ''), '未知') AS group_key, "
            "COALESCE(NULLIF(t.model, ''), '未知') AS group_name",
            "t.model",
        )
    if dimension == "source":
        return (
            "COALESCE(NULLIF(t.source, ''), '未知') AS group_key, "
            "COALESCE(NULLIF(t.source, ''), '未知') AS group_name",
            "t.source",
        )
    return (
        "date(tr.ts, 'unixepoch', 'localtime') AS group_key, "
        "date(tr.ts, 'unixepoch', 'localtime') AS group_name",
        "date(tr.ts, 'unixepoch', 'localtime')",
    )


def grouped(
    conn: sqlite3.Connection,
    start: Optional[int],
    end: Optional[int],
    dimension: str = "project",
    project_key: Optional[str] = None,
    provider: Optional[str] = None,
    limit: Optional[int] = None,
) -> List[Dict[str, Any]]:
    expression, group_by = _group_expression(dimension)
    base, params = _join(start, end, project_key, provider)
    sums = ", ".join(
        f"COALESCE(SUM(tr.{column}), 0) AS {column}" for column in USAGE_COLUMNS
    )
    sql = f"""
        SELECT {expression},
               COUNT(DISTINCT t.id) AS task_count,
               COUNT(tr.id) AS turn_count,
               {UNPRICED_TASK_SQL},
               {sums},
               {cost_sql()}
        {base}
        GROUP BY {group_by}
        ORDER BY total_tokens DESC
    """
    if limit:
        sql += " LIMIT ?"
        params.append(int(limit))
    result = [dict(row) for row in conn.execute(sql, params).fetchall()]
    if dimension == "model":
        for row in result:
            row["group_name"] = display_model(row.get("group_key", ""))
    return result


def tasks(
    conn: sqlite3.Connection,
    start: Optional[int],
    end: Optional[int],
    project_key: Optional[str] = None,
    provider: Optional[str] = None,
    query: str = "",
    limit: int = 20,
    offset: int = 0,
) -> Tuple[List[Dict[str, Any]], int]:
    base, params = _join(start, end, project_key, provider, query)
    sums = ", ".join(
        f"COALESCE(SUM(tr.{column}), 0) AS {column}" for column in USAGE_COLUMNS
    )
    sql = f"""
        SELECT t.id, t.title, t.cwd, t.provider, t.model, t.source,
               t.created_at, t.updated_at, t.total_tokens AS all_total_tokens,
               p.key AS project_key, p.name AS project_name,
               COUNT(tr.id) AS turn_count,
               {sums}
        {base}
        GROUP BY t.id
        ORDER BY total_tokens DESC
        LIMIT ? OFFSET ?
    """
    rows = conn.execute(sql, params + [int(limit), int(offset)]).fetchall()
    total = conn.execute(
        f"SELECT COUNT(DISTINCT t.id) {base}", params
    ).fetchone()[0]
    result = []
    for row in rows:
        item = dict(row)
        item["model_display"] = display_model(item.get("model", ""))
        item["cost_cny"] = cost_from_row(item)
        result.append(item)
    return result, int(total)


def task_detail(conn: sqlite3.Connection, task_id: str) -> Optional[Dict[str, Any]]:
    row = conn.execute(
        """
        SELECT t.id, t.title, t.cwd, t.provider, t.model, t.source,
               t.created_at, t.updated_at, t.total_input_tokens,
               t.total_cached_input_tokens, t.total_cache_write_input_tokens,
               t.total_output_tokens, t.total_reasoning_output_tokens,
               t.total_tokens, t.turn_count, t.status, t.rollout_path,
               p.key AS project_key, p.name AS project_name
        FROM tasks t
        LEFT JOIN projects p ON p.id = t.project_id
        WHERE t.id = ?
        """,
        (task_id,),
    ).fetchone()
    if not row:
        return None
    result = dict(row)
    result["input_tokens"] = result["total_input_tokens"]
    result["cached_input_tokens"] = result["total_cached_input_tokens"]
    result["cache_write_input_tokens"] = result["total_cache_write_input_tokens"]
    result["output_tokens"] = result["total_output_tokens"]
    result["reasoning_output_tokens"] = result["total_reasoning_output_tokens"]
    result["model_display"] = display_model(result.get("model", ""))
    result["cost_cny"] = cost_from_row(result)
    return result


def task_turns(conn: sqlite3.Connection, task_id: str) -> List[Dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT tr.turn_index, tr.ts, tr.input_tokens, tr.cached_input_tokens,
               tr.cache_write_input_tokens, tr.output_tokens,
               tr.reasoning_output_tokens, tr.total_tokens, t.model
        FROM turns tr
        JOIN tasks t ON t.id = tr.task_id
        WHERE tr.task_id = ?
        ORDER BY turn_index
        """,
        (task_id,),
    ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["model_display"] = display_model(item.get("model", ""))
        item["cost_cny"] = cost_from_row(item)
        result.append(item)
    return result


def filters(conn: sqlite3.Connection) -> Dict[str, Any]:
    projects = conn.execute(
        """
        SELECT COALESCE(p.name, '未知') AS key,
               COALESCE(p.name, '未知') AS name
        FROM tasks t
        LEFT JOIN projects p ON p.id = t.project_id
        WHERE COALESCE(p.name, '') <> ''
        GROUP BY COALESCE(p.name, '未知')
        ORDER BY COALESCE(p.name, '未知')
        """
    ).fetchall()
    providers = conn.execute(
        "SELECT DISTINCT provider FROM tasks WHERE provider <> '' ORDER BY provider"
    ).fetchall()
    models = conn.execute(
        "SELECT DISTINCT model FROM tasks WHERE model <> '' ORDER BY model"
    ).fetchall()
    sources = conn.execute(
        "SELECT DISTINCT source FROM tasks WHERE source <> '' ORDER BY source"
    ).fetchall()
    return {
        "projects": [dict(row) for row in projects],
        "providers": [row["provider"] for row in providers],
        "models": [row["model"] for row in models],
        "sources": [row["source"] for row in sources],
    }
