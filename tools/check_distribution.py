"""Check the exact release artifacts without extracting or running their code."""
from __future__ import annotations

import argparse
from email.parser import BytesParser
import hashlib
import importlib.util
import json
from pathlib import Path, PurePosixPath
import stat
import tarfile
import zipfile

_spec = importlib.util.spec_from_file_location("release_public_audit", Path(__file__).with_name("export_public_repo.py"))
_audit = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_audit)

PACKAGE = "commerce_agent_eval"
SOURCE_ROOTS = {"src", "examples"}
SOURCE_FILES = {"pyproject.toml", "README.pypi.md", "LICENSE", "PKG-INFO", ".gitignore"}


def check_path(name: str) -> PurePosixPath:
    path = PurePosixPath(name)
    if not name or path.is_absolute() or ".." in path.parts or "\\" in name or ":" in name:
        raise ValueError("unsafe_archive_path")
    if any(part.startswith(".") for part in path.parts[:-1]) or (
        path.name.startswith(".") and path.name != ".gitignore"
    ) or any(part in {"runs", "node_modules", "__pycache__"} for part in path.parts):
        raise ValueError("private_archive_path")
    if path.suffix in {".db", ".sqlite", ".sqlite3", ".pyc"}:
        raise ValueError("runtime_data_in_distribution")
    return path


def validate_members(members: dict[str, bytes], kind: str, version: str) -> None:
    info_dir = f"{PACKAGE}-{version}.dist-info"
    for name, content in members.items():
        path = check_path(name)
        if kind == "wheel":
            if path.parts[0] not in {"commerce_eval", info_dir}:
                raise ValueError("unexpected_wheel_member")
        elif path.parts[0] not in SOURCE_ROOTS and name not in SOURCE_FILES:
            raise ValueError("unexpected_sdist_member")
        _audit.audit_file(Path(name), content)
    if kind == "wheel":
        required = {
            f"{info_dir}/METADATA", f"{info_dir}/WHEEL", f"{info_dir}/entry_points.txt",
            f"{info_dir}/licenses/LICENSE", "commerce_eval/__init__.py",
            "commerce_eval/static/index.html", "commerce_eval/demo_data/dataset.jsonl",
            "commerce_eval/demo_data/tool-contracts.json", "commerce_eval/demo_data/traces.jsonl",
        }
        metadata_path = f"{info_dir}/METADATA"
    else:
        required = (SOURCE_FILES - {".gitignore"}) | {"src/commerce_eval/__init__.py",
            "src/commerce_eval/static/index.html", "examples/dataset.jsonl",
            "examples/tool-contracts.json", "examples/traces.jsonl"}
        metadata_path = "PKG-INFO"
    if not required <= members.keys():
        raise ValueError("required_distribution_member_missing")
    metadata = BytesParser().parsebytes(members[metadata_path])
    if metadata["Name"] != "commerce-agent-eval" or metadata["Version"] != version:
        raise ValueError("release_metadata_mismatch")
    if metadata["Requires-Python"] != ">=3.10":
        raise ValueError("python_requirement_mismatch")
    if metadata["Description-Content-Type"] != "text/markdown":
        raise ValueError("readme_content_type_missing")
    if not any(name.endswith(".js") and "/static/assets/" in name for name in members):
        raise ValueError("frontend_bundle_missing")


def inspect_distribution(file: Path, version: str) -> dict:
    members = {}
    if file.suffix == ".whl":
        kind = "wheel"
        with zipfile.ZipFile(file) as archive:
            for info in archive.infolist():
                check_path(info.filename)
                if stat.S_ISLNK(info.external_attr >> 16):
                    raise ValueError("archive_link_not_allowed")
                if not info.is_dir():
                    if info.filename in members:
                        raise ValueError("duplicate_archive_member")
                    members[info.filename] = archive.read(info)
    else:
        kind = "sdist"
        prefix = f"{PACKAGE}-{version}/"
        with tarfile.open(file, "r:gz") as archive:
            for info in archive:
                check_path(info.name)
                if not info.name.startswith(prefix) or (not info.isfile() and not info.isdir()):
                    raise ValueError("invalid_sdist_member")
                if info.isfile():
                    name = info.name[len(prefix):]
                    if name in members:
                        raise ValueError("duplicate_archive_member")
                    members[name] = archive.extractfile(info).read()
    validate_members(members, kind, version)
    return {"file": file.name, "kind": kind, "members": len(members),
            "sha256": hashlib.sha256(file.read_bytes()).hexdigest(), "bytes": file.stat().st_size}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--version", required=True)
    args = parser.parse_args()
    files = sorted(args.directory.iterdir())
    if len(files) != 2 or sum(f.suffix == ".whl" for f in files) != 1 or sum(f.name.endswith(".tar.gz") for f in files) != 1:
        raise ValueError("expected_exactly_one_wheel_and_sdist")
    records = [inspect_distribution(file, args.version) for file in files]
    print(json.dumps({"version": args.version, "status": "valid", "artifacts": records}, indent=2))


if __name__ == "__main__":
    main()
