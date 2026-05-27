from __future__ import annotations

from pathlib import PurePosixPath


def safe_workspace_path(path: str | None, *, workspace_root: str) -> str:
    root = PurePosixPath(workspace_root)
    candidate = root if not path else PurePosixPath(path)
    if not candidate.is_absolute():
        candidate = root / candidate

    normalized = PurePosixPath("/")
    for part in candidate.parts:
        if part in {"", "/"}:
            continue
        if part == "..":
            raise RuntimeError("Path traversal is not allowed")
        if part == ".":
            continue
        normalized = normalized / part

    if normalized != root and root not in normalized.parents:
        raise RuntimeError(f"Path must stay under {workspace_root}")
    return str(normalized)
