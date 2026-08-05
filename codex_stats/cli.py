from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import db, queries, scanner
from .config import Config, load_config, project_root


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--codex-home", help="Codex 数据目录，默认 ~/.codex")
    parser.add_argument("--db", help="统计数据库路径，默认工具目录下 codex_stats.db")


def _resolve_config(args) -> Config:
    cfg = load_config()
    if getattr(args, "codex_home", None):
        cfg.codex_home = args.codex_home
    if getattr(args, "db", None):
        cfg.db_path = args.db
    return cfg


def _db_path(cfg: Config) -> Path:
    if cfg.db_path:
        return Path(cfg.db_path)
    return project_root() / "codex_stats.db"


def cmd_scan(args) -> int:
    cfg = _resolve_config(args)
    conn = db.connect(_db_path(cfg))
    try:
        result = scanner.scan(conn, config=cfg)
    finally:
        conn.close()
    print(f"已扫描 {result['scanned']} 个会话文件，跳过 {result['skipped']} 个未变化的文件")
    print(f"数据目录: {result['codex_home']}")
    return 0


def cmd_report(args) -> int:
    cfg = _resolve_config(args)
    conn = db.connect(_db_path(cfg))
    try:
        db.init_db(conn)
        from . import report

        report.run_report(conn, args, cfg)
    finally:
        conn.close()
    return 0


def cmd_serve(args) -> int:
    cfg = _resolve_config(args)
    if args.host:
        cfg.host = args.host
    if args.port:
        cfg.port = args.port
    db_path = _db_path(cfg)
    conn = db.connect(db_path)
    try:
        result = scanner.scan(conn, config=cfg)
    finally:
        conn.close()
    print(f"启动前扫描: {result['scanned']} 个文件，跳过 {result['skipped']} 个")

    from .web import serve

    serve(db_path, cfg)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="codex-stats",
        description="Codex 本地 token 用量统计工具",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    scan_p = sub.add_parser("scan", help="扫描 Codex 会话并写入统计库")
    _add_common(scan_p)

    report_p = sub.add_parser("report", help="输出 token 统计报表")
    _add_common(report_p)
    report_p.add_argument(
        "--period",
        default="all",
        choices=["today", "yesterday", "7d", "30d", "week", "month", "year", "all"],
        help="统计时段，默认 all",
    )
    report_p.add_argument("--from", dest="from_date", help="开始时间 YYYY-MM-DD 或 YYYY-MM-DD HH:MM")
    report_p.add_argument("--to", dest="to_date", help="结束时间 YYYY-MM-DD 或 YYYY-MM-DD HH:MM")
    report_p.add_argument("--from-date", dest="from_date", help="开始时间别名，同 --from")
    report_p.add_argument("--to-date", dest="to_date", help="结束时间别名，同 --to")
    report_p.add_argument(
        "--dimension",
        default="overall",
        choices=["overall", "project", "provider", "model", "source", "day", "task"],
        help="统计维度，默认 overall",
    )
    report_p.add_argument("--project", help="按项目 key 过滤")
    report_p.add_argument("--provider", help="按供应商过滤")
    report_p.add_argument("--limit", type=int, default=20, help="最多显示行数")
    report_p.add_argument("--csv", help="导出 CSV 文件路径")
    report_p.add_argument("--json", help="导出 JSON 文件路径")

    serve_p = sub.add_parser("serve", help="启动本地网页统计面板")
    _add_common(serve_p)
    serve_p.add_argument("--host", help="监听地址，默认 127.0.0.1")
    serve_p.add_argument("--port", type=int, help="监听端口，默认 8765")
    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "scan":
        return cmd_scan(args)
    if args.command == "report":
        return cmd_report(args)
    if args.command == "serve":
        return cmd_serve(args)
    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
