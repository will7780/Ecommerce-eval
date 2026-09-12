"""Small isolated data workspace; never a shell or an operating-system sandbox."""

from __future__ import annotations

import os
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory

from commerce_eval.scenarios.artifacts import safe_artifact_name


class BusinessWorkspace:
    MAX_FILE_BYTES = 1_000_000
    MAX_TOTAL_BYTES = 5_000_000

    def __init__(self, root: str | Path | None = None):
        if root is not None:
            Path(root).mkdir(parents=True, exist_ok=True)
        self._directory = TemporaryDirectory(prefix="business-case-", dir=root)
        self.root = Path(self._directory.name).resolve()
        for name in ("inputs", "artifacts", "frozen"):
            (self.root / name).mkdir()

    def resolve(self, name: str, *, writable: bool = False, internal: bool = False) -> Path:
        if not isinstance(name, str) or not name or "\\" in name or ":" in name or "\x00" in name:
            raise ValueError("workspace_path_denied")
        raw_parts = name.split("/")
        path = PurePosixPath(name)
        if path.is_absolute() or any(part in {"", ".", ".."} for part in raw_parts):
            raise ValueError("workspace_path_denied")
        permitted = {"inputs", "artifacts", "frozen"} if internal else {"inputs", "artifacts"}
        if path.parts[0] not in permitted or (writable and not internal and path.parts[0] != "artifacts"):
            raise ValueError("workspace_path_denied")
        current = self.root
        for part in path.parts:
            safe_artifact_name(part)
            if part.startswith("."):
                raise ValueError("workspace_path_denied")
            current = current / part
            if current.is_symlink() or (hasattr(current, "is_junction") and current.is_junction()):
                raise ValueError("workspace_link_denied")
            if current.exists() and current.is_file() and current.stat().st_nlink > 1:
                raise ValueError("workspace_link_denied")
        if not current.resolve().is_relative_to(self.root):
            raise ValueError("workspace_path_denied")
        return current

    def read(self, name: str, *, internal: bool = False) -> str:
        path = self.resolve(name, internal=internal)
        if not path.is_file():
            raise ValueError("input_file_missing")
        if path.stat().st_size > self.MAX_FILE_BYTES:
            raise ValueError("workspace_file_too_large")
        try:
            with path.open("rb") as stream:
                content = stream.read(self.MAX_FILE_BYTES + 1)
            if len(content) > self.MAX_FILE_BYTES:
                raise ValueError("workspace_file_too_large")
            return content.decode("utf-8")
        except UnicodeError as exc:
            raise ValueError("workspace_format_unavailable") from exc

    def list(self, name: str = "artifacts", *, internal: bool = False) -> list[str]:
        path = self.resolve(name, internal=internal)
        if not path.is_dir():
            raise ValueError("workspace_directory_missing")
        result = []
        for directory, dirs, files in os.walk(path, followlinks=False):
            for member in [*dirs, *files]:
                relative = (Path(directory) / member).relative_to(self.root).as_posix()
                self.resolve(relative, internal=internal)
            result.extend((Path(directory) / member).relative_to(self.root).as_posix() for member in files)
        return sorted(result)

    def write(self, name: str, content: str, *, internal: bool = False) -> None:
        if not isinstance(content, str):
            raise ValueError("workspace_content_invalid")
        encoded = content.encode("utf-8")
        if len(encoded) > self.MAX_FILE_BYTES:
            raise ValueError("workspace_file_too_large")
        path = self.resolve(name, writable=True, internal=internal)
        if path.suffix.lower() not in {".json", ".csv", ".txt", ".md"}:
            raise ValueError("workspace_format_unavailable")
        visible = self.list("inputs") + self.list("artifacts")
        total = sum(self.resolve(item).stat().st_size for item in visible if self.resolve(item) != path)
        if total + len(encoded) > self.MAX_TOTAL_BYTES:
            raise ValueError("workspace_total_too_large")
        path.parent.mkdir(parents=True, exist_ok=True)
        # File members and their parents are checked again after directory creation.
        self.resolve(name, writable=True, internal=internal)
        path.write_bytes(encoded)

    def close(self) -> None:
        # TemporaryDirectory owns this exact, independently created directory.
        self._directory.cleanup()
