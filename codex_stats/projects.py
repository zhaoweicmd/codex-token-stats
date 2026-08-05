from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Dict, Optional, Tuple

from .config import Config
from .models import ProjectInfo

_REPO_URL_RE = re.compile(
    r"(?:https?://|git@)(?:www\.)?"
    r"(?:github\.com|gitee\.com|gitlab\.com|bitbucket\.org)"
    r"[:/]([^/\s]+)/([^/\s?#]+)"
)


class ProjectResolver:
    def __init__(self, config: Config):
        self.aliases = list(config.project_aliases or [])
        self.rules = list(config.project_rules or [])
        self.default_project = (config.default_project or "").strip()
        self.cache: Dict[str, ProjectInfo] = {}

    def resolve(self, cwd: str, git_url: str = "", title: str = "") -> ProjectInfo:
        cwd = (cwd or "").strip()
        cache_key = (os.path.normcase(cwd) if cwd else "<unknown>", title or "")
        if cache_key in self.cache:
            return self.cache[cache_key]

        alias = self._match_alias(cwd)
        if alias is not None:
            info = alias
            self.cache[cache_key] = info
            return info

        rule_project = self._match_rules(cwd, title)
        if rule_project is not None:
            self.cache[cache_key] = rule_project
            return rule_project

        if self.default_project:
            info = ProjectInfo(
                key=f"default:{self.default_project}",
                name=self.default_project,
                kind="default",
                path=cwd,
            )
            self.cache[cache_key] = info
            return info

        title_info = self._resolve_from_title(cwd, title)
        if title_info is not None:
            self.cache[cache_key] = title_info
            return title_info

        info = self._resolve_git(cwd, git_url)
        if info is None:
            name = Path(cwd).name if cwd and Path(cwd).name else ("未知" if not cwd else cwd)
            info = ProjectInfo(
                key=os.path.normcase(cwd) if cwd else "unknown",
                name=name,
                kind="cwd",
                path=cwd,
            )
        self.cache[cache_key] = info
        return info

    def _match_rules(self, cwd: str, title: str) -> Optional[ProjectInfo]:
        for rule in self.rules:
            rule_type = str(rule.get("type", "") or "").strip()
            pattern = str(rule.get("pattern", "") or "").strip()
            name = str(rule.get("name", "") or "").strip()
            if not pattern or not name:
                continue
            matched = False
            if rule_type == "path":
                norm = os.path.normcase
                target = norm(pattern)
                current = norm(cwd)
                matched = current == target or current.startswith(target + os.sep)
            elif rule_type == "title":
                try:
                    matched = re.search(pattern, title or "") is not None
                except re.error:
                    matched = False
            if matched:
                return ProjectInfo(
                    key=f"rule:{name}",
                    name=name,
                    kind="rule",
                    path=cwd,
                )
        return None

    def _resolve_from_title(self, cwd: str, title: str) -> Optional[ProjectInfo]:
        match = _REPO_URL_RE.search(title or "")
        if not match:
            return None
        owner = match.group(1)
        repo = match.group(2)
        if repo.endswith(".git"):
            repo = repo[:-4]
        if not owner or not repo:
            return None
        return ProjectInfo(
            key=f"title:{owner}/{repo}",
            name=repo,
            kind="title",
            path=cwd,
        )

    def _match_alias(self, cwd: str) -> Optional[ProjectInfo]:
        best: Optional[ProjectInfo] = None
        best_len = -1
        for item in self.aliases:
            raw_path = str(item.get("path", "") or "").strip()
            name = str(item.get("name", "") or "").strip() or None
            if not raw_path or not name:
                continue
            norm = os.path.normcase
            target = norm(raw_path)
            current = norm(cwd)
            matched = current == target or current.startswith(target + os.sep)
            if matched and len(target) > best_len:
                best_len = len(target)
                best = ProjectInfo(
                    key=target,
                    name=name,
                    kind="alias",
                    path=raw_path,
                )
        return best

    def _resolve_git(self, cwd: str, git_url: str) -> Optional[ProjectInfo]:
        if git_url:
            url = normalize_git_url(git_url)
            name = repo_name(git_url)
            return ProjectInfo(
                key=url,
                name=name,
                kind="git",
                path=cwd,
                git_url=git_url,
            )
        if not cwd or not Path(cwd).exists():
            return None
        root = _git_toplevel(cwd)
        if not root:
            return None
        url = _git_origin_url(root)
        if url:
            return ProjectInfo(
                key=normalize_git_url(url),
                name=repo_name(url),
                kind="git",
                path=cwd,
                git_url=url,
            )
        if cwd != root:
            return ProjectInfo(
                key=os.path.normcase(cwd),
                name=Path(cwd).name or cwd,
                kind="cwd",
                path=cwd,
            )
        return ProjectInfo(
            key=os.path.normcase(root),
            name=Path(root).name or root,
            kind="git",
            path=cwd,
        )


def _git_toplevel(cwd: str) -> Optional[str]:
    try:
        result = subprocess.run(
            ["git", "-C", cwd, "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    value = result.stdout.strip()
    return value or None


def _git_origin_url(root: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", root, "config", "--get", "remote.origin.url"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout.strip()


def normalize_git_url(url: str) -> str:
    value = (url or "").strip().rstrip("/")
    if not value:
        return value
    if value.endswith(".git"):
        value = value[:-4]
    if value.startswith("git@"):
        value = value.replace(":", "/", 1)
    return value.lower()


def repo_name(url: str) -> str:
    value = normalize_git_url(url)
    if not value:
        return "未知仓库"
    name = value.rsplit("/", 1)[-1]
    return name or "未知仓库"
