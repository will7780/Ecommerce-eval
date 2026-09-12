"""Export a reviewed public source snapshot, never runtime data or credentials."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil


ROOT_FILES = {
    ".dockerignore", ".env.example", ".gitattributes", ".gitignore", "AGENTS.md", "CONTRIBUTING.md",
    "Dockerfile", "LICENSE", "README.md", "README.en.md", "SECURITY.md",
    "alembic.ini", "pyproject.toml",
}
PUBLIC_DESIGNS = {"PUBLIC_ARCHITECTURE.md", "GITHUB_PUBLIC_RELEASE.md"}
SKIP_DIRS = {
    ".git", ".venv", "__pycache__", ".pytest_cache", "node_modules", "runs",
    "dist", "build", "test-results", "playwright-report", ".agents", ".codex",
}
SOURCE_EXTENSIONS = {".py", ".json", ".jsonl", ".html", ".js", ".css"}
TEXT_EXTENSIONS = SOURCE_EXTENSIONS | {".md", ".yaml", ".yml", ".ts", ".tsx", ".cjs", ".toml", ".ini", ".mako", ".example"}
SECRET = re.compile(
    r"sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}"
    r"|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|AKIA[A-Z0-9]{16}"
)
PERSONAL_PATH = re.compile(r"(?i)[a-z]:[/\\]+Users[/\\]+(?!someone[/\\]|example[/\\])[^/\\\s]+")
URL_CREDENTIAL = re.compile(r"https?://[^/\s:@]+:[^/\s@]+@([^/\s\"']+)")
SECURITY_URL_FIXTURES = {"tests/test_onboarding_import_services.py", "tests/test_providers_v030.py"}


def is_public(relative: Path) -> bool:
    parts = relative.parts
    if not parts or any(part in SKIP_DIRS for part in parts):
        return False
    if len(parts) == 1:
        return relative.name in ROOT_FILES
    first = parts[0]
    if first == "docs":
        return (
            (len(parts) == 2 and relative.suffix == ".md")
            or (len(parts) == 3 and parts[1] == "design" and relative.name in PUBLIC_DESIGNS)
            or (len(parts) == 4 and parts[1:3] == ("assets", "readme") and relative.suffix == ".png")
            or relative.as_posix() == "docs/assets/readme/banner.svg"
        )
    if first == ".github":
        return len(parts) == 3 and parts[1] == "workflows" and relative.suffix in {".yml", ".yaml"}
    if first == "src":
        return len(parts) >= 3 and parts[1] == "commerce_eval" and relative.suffix in SOURCE_EXTENSIONS
    if first == "skills":
        return len(parts) >= 3 and parts[1] == "ecommerce-eval-onboarding" and (
            relative.suffix in {".md", ".py", ".json", ".yaml", ".yml"} or relative.name == ".gitattributes"
        )
    if first == "tests":
        return relative.suffix == ".py" or ("fixtures" in parts and relative.suffix in {".md", ".json"})
    if first == "examples":
        return relative.suffix in {".json", ".jsonl"}
    if first == "migrations":
        return relative.suffix in {".py", ".mako"}
    if first == "tools":
        return len(parts) == 2 and relative.suffix in {".py", ".cjs"}
    if first == "web":
        return (
            (len(parts) == 2 and relative.suffix in {".json", ".ts", ".html"} and not relative.name.endswith(".d.ts"))
            or (len(parts) > 2 and parts[1] in {"src", "tests"} and relative.suffix in {".ts", ".tsx", ".css"})
        )
    return False


def audit_file(relative: Path, content: bytes) -> None:
    if relative.suffix == ".png":
        if not content.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValueError(f"invalid_image: {relative.as_posix()}")
        return
    text = content.decode("utf-8-sig")
    if SECRET.search(text) or PERSONAL_PATH.search(text):
        raise ValueError(f"sensitive_pattern: {relative.as_posix()}")
    for match in URL_CREDENTIAL.finditer(text):
        if relative.as_posix() not in SECURITY_URL_FIXTURES or match.group(1) != "example.com":
            raise ValueError(f"credential_url: {relative.as_posix()}")
    if relative.name == ".env.example":
        for line in text.splitlines():
            if line.strip() and not line.lstrip().startswith("#") and "=" in line:
                name, value = line.split("=", 1)
                if any(term in name.upper() for term in ("KEY", "TOKEN", "PASSWORD", "SECRET")) and value.strip():
                    raise ValueError("nonempty_credential_example")


def export_public(source: Path, destination: Path) -> dict:
    source = source.resolve(strict=True)
    destination = destination.absolute()
    if destination.exists() or destination.is_symlink():
        raise FileExistsError("Export requires a new destination; existing data is never overwritten")
    if destination.resolve().is_relative_to(source):
        raise ValueError("destination_must_be_outside_source")
    # Inspect every approved file before creating or copying the public snapshot.
    approved: list[tuple[Path, str]] = []
    for directory, dirs, files in os.walk(source, followlinks=False):
        dirs[:] = sorted(name for name in dirs if name not in SKIP_DIRS and not name.endswith(".egg-info"))
        for name in dirs:
            child = Path(directory) / name
            if child.is_symlink() or (hasattr(child, "is_junction") and child.is_junction()):
                raise ValueError("source_link_not_allowed")
        for name in sorted(files):
            path = Path(directory) / name
            relative = path.relative_to(source)
            if not is_public(relative):
                continue
            if path.is_symlink() or not path.resolve().is_relative_to(source):
                raise ValueError("source_link_not_allowed")
            content = path.read_bytes()
            audit_file(relative, content)
            approved.append((relative, hashlib.sha256(content).hexdigest()))
    required = {"pyproject.toml", "LICENSE", "README.md", "src/commerce_eval/static/index.html", "skills/ecommerce-eval-onboarding/SKILL.md"}
    if not required.issubset({path.as_posix() for path, _ in approved}):
        raise ValueError("incomplete_public_source")
    destination.mkdir(parents=True, exist_ok=False)
    records = []
    for relative, digest in sorted(approved):
        original = source / relative
        if hashlib.sha256(original.read_bytes()).hexdigest() != digest:
            raise ValueError(f"source_changed_during_export: {relative.as_posix()}")
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(original, target)
        if hashlib.sha256(target.read_bytes()).hexdigest() != digest:
            raise ValueError("copy_digest_mismatch")
        records.append({"path": relative.as_posix(), "sha256": digest})
    manifest = {"schema_version": 1, "purpose": "public source snapshot, not runtime data", "files": records}
    (destination / "PUBLIC_EXPORT_MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    manifest = export_public(args.source, args.destination)
    print(json.dumps({"file_count": len(manifest["files"]), "status": "exported"}))


if __name__ == "__main__":
    main()
