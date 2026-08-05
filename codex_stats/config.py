from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class Config:
    codex_home: Optional[str] = None
    db_path: Optional[str] = None
    host: str = "127.0.0.1"
    port: int = 8765
    scan_interval: int = 60
    provider_names: Dict[str, str] = field(default_factory=dict)
    project_aliases: List[Dict[str, str]] = field(default_factory=list)
    project_rules: List[Dict[str, str]] = field(default_factory=list)
    project_rules_mac: List[Dict[str, str]] = field(default_factory=list)
    project_rules_win: List[Dict[str, str]] = field(default_factory=list)
    default_project: str = ""
    default_project_mac: str = ""
    default_project_win: str = ""


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def load_config(path: Optional[Path] = None) -> Config:
    cfg = Config()
    p = Path(path) if path is not None else project_root() / "config.json"
    if not p.exists():
        return cfg
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return cfg
    if not isinstance(data, dict):
        return cfg
    for key in ("codex_home", "db_path", "host"):
        if isinstance(data.get(key), str):
            setattr(cfg, key, data[key])
    if isinstance(data.get("port"), int):
        cfg.port = data["port"]
    if isinstance(data.get("scan_interval"), int) and data["scan_interval"] > 0:
        cfg.scan_interval = data["scan_interval"]
    if isinstance(data.get("provider_names"), dict):
        cfg.provider_names = {
            str(k): str(v) for k, v in data["provider_names"].items()
        }
    if isinstance(data.get("project_aliases"), list):
        cfg.project_aliases = [
            item for item in data["project_aliases"] if isinstance(item, dict)
        ]
    if isinstance(data.get("project_rules"), list):
        cfg.project_rules = [
            item for item in data["project_rules"] if isinstance(item, dict)
        ]
    if isinstance(data.get("project_rules_mac"), list):
        cfg.project_rules_mac = [
            item for item in data["project_rules_mac"] if isinstance(item, dict)
        ]
    if isinstance(data.get("project_rules_win"), list):
        cfg.project_rules_win = [
            item for item in data["project_rules_win"] if isinstance(item, dict)
        ]
    if isinstance(data.get("default_project"), str):
        cfg.default_project = data["default_project"].strip()
    if isinstance(data.get("default_project_mac"), str):
        cfg.default_project_mac = data["default_project_mac"].strip()
    if isinstance(data.get("default_project_win"), str):
        cfg.default_project_win = data["default_project_win"].strip()

    if sys.platform == "win32":
        if cfg.default_project_win:
            cfg.default_project = cfg.default_project_win
        if cfg.project_rules_win:
            cfg.project_rules = cfg.project_rules_win
    elif sys.platform == "darwin":
        if cfg.default_project_mac:
            cfg.default_project = cfg.default_project_mac
        if cfg.project_rules_mac:
            cfg.project_rules = cfg.project_rules_mac
    return cfg
