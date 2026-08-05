from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Dict, Optional
from urllib.parse import parse_qs, urlsplit

from . import db, queries, scanner
from .config import Config

WEBUI_DIR = Path(__file__).resolve().parent / "webui"
_scan_lock = threading.Lock()


def _parse_params(path: str) -> Dict[str, str]:
    query = urlsplit(path).query
    parsed = parse_qs(query)
    return {key: values[0] for key, values in parsed.items()}


def _display_provider(provider: str, config: Config) -> str:
    if provider in config.provider_names:
        return config.provider_names[provider]
    return provider or "未知"


def _attach_provider_names(rows: list, config: Config) -> list:
    for row in rows:
        row["display_name"] = _display_provider(row.get("group_key", ""), config)
    return rows


def _scan_now(db_path: Path, config: Config) -> dict:
    with _scan_lock:
        conn = db.connect(db_path)
        try:
            return scanner.scan(conn, config=config)
        finally:
            conn.close()


def make_handler(db_path: Path, config: Config):
    class StatsHandler(BaseHTTPRequestHandler):
        server_version = "CodexStats/0.1"

        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, data, status: int = 200) -> None:
            body = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self._send(status, body, "application/json; charset=utf-8")

        def _static(self, name: str) -> None:
            target = WEBUI_DIR / name
            if not target.is_file():
                self._json({"error": "not found"}, 404)
                return
            if name.endswith(".css"):
                content_type = "text/css; charset=utf-8"
            elif name.endswith(".js"):
                content_type = "application/javascript; charset=utf-8"
            else:
                content_type = "text/html; charset=utf-8"
            self._send(200, target.read_bytes(), content_type)

        def _conn(self):
            return db.connect(db_path)

        def _api_summary(self, params: Dict[str, str]) -> dict:
            start, end = queries.period_range(
                params.get("period", "all"),
                params.get("from", ""),
                params.get("to", ""),
            )
            project = params.get("project") or None
            provider = params.get("provider") or None
            conn = self._conn()
            try:
                summary = queries.summary(conn, start, end, project, provider)
                trend = queries.grouped(
                    conn, start, end, "day", project, provider, limit=None
                )
                projects = queries.grouped(
                    conn, start, end, "project", project, provider, limit=10
                )
                providers = _attach_provider_names(
                    queries.grouped(
                        conn, start, end, "provider", project, provider, limit=10
                    ),
                    config,
                )
                models = queries.grouped(
                    conn, start, end, "model", project, provider, limit=10
                )
                sources = queries.grouped(
                    conn, start, end, "source", project, provider, limit=8
                )
                latest, _ = queries.tasks(
                    conn, start, end, project, provider, limit=8
                )
            finally:
                conn.close()
            return {
                "period_label": queries.period_label(start, end),
                "start": start,
                "end": end,
                "summary": summary,
                "trend": trend,
                "projects": projects,
                "providers": providers,
                "models": models,
                "sources": sources,
                "latest_tasks": latest,
            }

        def _api_tasks(self, params: Dict[str, str]) -> dict:
            start, end = queries.period_range(
                params.get("period", "all"),
                params.get("from", ""),
                params.get("to", ""),
            )
            conn = self._conn()
            try:
                items, total = queries.tasks(
                    conn,
                    start,
                    end,
                    params.get("project") or None,
                    params.get("provider") or None,
                    query=params.get("q", ""),
                    limit=int(params.get("limit", "20") or 20),
                    offset=int(params.get("offset", "0") or 0),
                )
            finally:
                conn.close()
            return {"items": items, "total": total}

        def _api_task(self, task_id: str, turns: bool) -> dict:
            conn = self._conn()
            try:
                detail = queries.task_detail(conn, task_id)
                if detail is None:
                    return {"error": "task not found"}
                if turns:
                    return {"task": detail, "turns": queries.task_turns(conn, task_id)}
                return {"task": detail}
            finally:
                conn.close()

        def _api_filters(self) -> dict:
            conn = self._conn()
            try:
                return queries.filters(conn)
            finally:
                conn.close()

        def _read_json_body(self) -> dict:
            try:
                length = int(self.headers.get("Content-Length", "0") or 0)
            except ValueError:
                length = 0
            if length <= 0:
                return {}
            try:
                data = json.loads(self.rfile.read(length).decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                return {}
            return data if isinstance(data, dict) else {}

        def _api_set_project(self, task_id: str) -> dict:
            payload = self._read_json_body()
            name = str(payload.get("project", "") or "").strip()
            conn = self._conn()
            try:
                db.init_db(conn)
                if name:
                    db.set_project_override(conn, task_id, name)
                else:
                    db.clear_project_override(conn, task_id)
                scanner.scan(conn, config=config)
                detail = queries.task_detail(conn, task_id)
                if detail is None:
                    return {"error": "task not found"}
                return {"task": detail}
            finally:
                conn.close()

        def do_GET(self) -> None:
            try:
                path = urlsplit(self.path).path
                if path == "/favicon.ico":
                    self._send(204, b"", "image/x-icon")
                    return
                if path in ("/", "/index.html"):
                    self._static("index.html")
                    return
                if path in ("/app.js", "/styles.css"):
                    self._static(path.lstrip("/"))
                    return
                if path == "/api/summary":
                    self._json(self._api_summary(_parse_params(self.path)))
                    return
                if path == "/api/tasks":
                    self._json(self._api_tasks(_parse_params(self.path)))
                    return
                if path == "/api/filters":
                    self._json(self._api_filters())
                    return
                if path.startswith("/api/tasks/"):
                    rest = path[len("/api/tasks/"):]
                    if rest.endswith("/turns"):
                        task_id = rest[: -len("/turns")]
                        self._json(self._api_task(task_id, True))
                        return
                    if "/" not in rest:
                        self._json(self._api_task(rest, False))
                        return
                self._json({"error": "not found"}, 404)
            except Exception as exc:  # pragma: no cover - defensive HTTP boundary
                self._json({"error": str(exc)}, 500)

        def do_POST(self) -> None:
            path = urlsplit(self.path).path
            if path == "/api/refresh":
                result = _scan_now(db_path, config)
                self._json({"result": result})
                return
            if path.startswith("/api/tasks/") and path.endswith("/project"):
                task_id = path[len("/api/tasks/") : -len("/project")]
                if task_id:
                    self._json(self._api_set_project(task_id))
                    return
            self._json({"error": "not found"}, 404)

        def log_message(self, format: str, *args) -> None:
            return

    return StatsHandler


def serve(db_path: Path, config: Config) -> None:
    handler = make_handler(db_path, config)
    server = ThreadingHTTPServer((config.host, config.port), handler)
    print(f"网页面板已启动: http://{config.host}:{config.port}")
    print(f"自动扫描间隔: {config.scan_interval} 秒")
    print("按 Ctrl+C 停止")
    stop_event = threading.Event()

    def auto_scan_loop():
        while not stop_event.wait(config.scan_interval):
            try:
                result = _scan_now(db_path, config)
                print(
                    f"自动扫描完成: 新增 {result['scanned']}，跳过 {result['skipped']}",
                    flush=True,
                )
            except Exception as exc:
                print(f"自动扫描失败: {exc}", flush=True)

    thread = threading.Thread(target=auto_scan_loop, daemon=True)
    thread.start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop_event.set()
        server.server_close()
