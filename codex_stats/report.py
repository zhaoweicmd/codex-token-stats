from __future__ import annotations

import csv
import json
import sqlite3
from typing import Any, Dict, List, Optional

from . import queries

COLUMN_LABELS = {
    "group_name": "维度",
    "task_count": "任务数",
    "turn_count": "轮次",
    "total_tokens": "总Token",
    "input_tokens": "输入",
    "output_tokens": "输出",
    "reasoning_output_tokens": "思考",
}


def _fmt(value) -> str:
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return str(value)


def _print_summary(data: Dict[str, Any]) -> None:
    print("总体统计")
    print(f"  任务数: {_fmt(data['task_count'])}")
    print(f"  轮次:   {_fmt(data['turn_count'])}")
    print(f"  总Token: {_fmt(data['total_tokens'])}")
    print(f"  输入:   {_fmt(data['input_tokens'])}")
    print(f"  缓存输入: {_fmt(data['cached_input_tokens'])}")
    print(f"  缓存写入: {_fmt(data['cache_write_input_tokens'])}")
    print(f"  输出:   {_fmt(data['output_tokens'])}")
    print(f"  思考输出: {_fmt(data['reasoning_output_tokens'])}")


def _print_table(rows: List[Dict[str, Any]], labels: Dict[str, str]) -> None:
    if not rows:
        print("  暂无数据")
        return
    columns = [
        "group_name",
        "task_count",
        "turn_count",
        "total_tokens",
        "input_tokens",
        "output_tokens",
        "reasoning_output_tokens",
    ]
    headers = [labels.get(column, column) for column in columns]
    lines = [[_fmt(row.get(column, "")) for column in columns] for row in rows]
    widths = [
        max(len(headers[i]), *(len(line[i]) for line in lines))
        for i in range(len(columns))
    ]
    print("  " + "  ".join(headers[i].ljust(widths[i]) for i in range(len(columns))))
    for line in lines:
        print(
            "  "
            + "  ".join(line[i].ljust(widths[i]) for i in range(len(columns)))
        )


def _write_csv(path: str, rows: List[Dict[str, Any]], labels: Dict[str, str]) -> None:
    if not rows:
        with open(path, "w", encoding="utf-8-sig", newline="") as handle:
            handle.write("")
        return
    fieldnames = list(labels.keys())
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with open(path, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writerow({key: labels.get(key, key) for key in fieldnames})
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def run_report(
    conn: sqlite3.Connection,
    args,
    config,
) -> Dict[str, Any]:
    start, end = queries.period_range(args.period, args.from_date or "", args.to_date or "")
    label = queries.period_label(start, end)
    dimension = args.dimension

    result: Dict[str, Any] = {
        "period_label": label,
        "start": start,
        "end": end,
        "dimension": dimension,
    }

    print(f"统计时段: {label}")
    if dimension == "overall":
        data = queries.summary(conn, start, end, args.project, args.provider)
        _print_summary(data)
        result["summary"] = data
    elif dimension == "task":
        rows, total = queries.tasks(
            conn,
            start,
            end,
            args.project,
            args.provider,
            query="",
            limit=args.limit,
        )
        if rows:
            print(f"任务数(含更多未显示): {total}")
            for row in rows:
                print(
                    f"  {_fmt(row['total_tokens']):>14}  "
                    f"{row.get('project_name') or '未知项目':<24} "
                    f"{(row.get('title') or '未命名任务')[:40]}"
                )
        else:
            print("  暂无数据")
        result["tasks"] = rows
    else:
        rows = queries.grouped(
            conn,
            start,
            end,
            dimension=dimension,
            project_key=args.project,
            provider=args.provider,
            limit=args.limit,
        )
        _print_table(rows, COLUMN_LABELS)
        result["rows"] = rows

    if args.csv:
        if dimension == "overall":
            _write_csv(args.csv, [result.get("summary", {})], COLUMN_LABELS)
        elif dimension == "task":
            _write_csv(args.csv, result.get("tasks", []), COLUMN_LABELS)
        else:
            _write_csv(args.csv, result.get("rows", []), COLUMN_LABELS)
        print(f"CSV 已写入: {args.csv}")
    if args.json:
        with open(args.json, "w", encoding="utf-8") as handle:
            json.dump(result, handle, ensure_ascii=False, indent=2)
        print(f"JSON 已写入: {args.json}")
    return result
