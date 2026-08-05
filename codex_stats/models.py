from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class TurnUsage:
    ts: int
    input_tokens: int = 0
    cached_input_tokens: int = 0
    cache_write_input_tokens: int = 0
    output_tokens: int = 0
    reasoning_output_tokens: int = 0
    total_tokens: int = 0


@dataclass
class ProjectInfo:
    key: str
    name: str
    kind: str = "cwd"
    path: str = ""
    git_url: str = ""


@dataclass
class TaskData:
    id: str
    title: str = ""
    cwd: str = ""
    provider: str = ""
    model: str = ""
    source: str = ""
    originator: str = ""
    cli_version: str = ""
    created_at: Optional[int] = None
    updated_at: Optional[int] = None
    rollout_path: str = ""
    status: str = "active"
    usage_source: str = "jsonl"
    project: Optional[ProjectInfo] = None
    turns: List[TurnUsage] = field(default_factory=list)
    fallback_total: Optional[int] = None
    git_url: str = ""
