"""Offline publication checks reject missing resources and unintended payloads."""
import importlib.util
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("check_distribution", ROOT / "tools/check_distribution.py")
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)

VERSION = "0.3.0rc2"


def members(kind):
    metadata = (f"Name: commerce-agent-eval\nVersion: {VERSION}\nRequires-Python: >=3.10\n"
                "Description-Content-Type: text/markdown\n\n# E-commerce Eval\n").encode()
    if kind == "wheel":
        info = f"commerce_agent_eval-{VERSION}.dist-info"
        return {
            f"{info}/METADATA": metadata, f"{info}/WHEEL": b"Wheel-Version: 1.0",
            f"{info}/entry_points.txt": b"commerce-eval = commerce_eval.cli:main",
            f"{info}/licenses/LICENSE": b"MIT", "commerce_eval/__init__.py": b"",
            "commerce_eval/static/index.html": b'<div id="root"></div>',
            "commerce_eval/static/assets/app.js": b"// bundled application",
            **{f"commerce_eval/demo_data/{name}": b"{}" for name in ("dataset.jsonl", "tool-contracts.json", "traces.jsonl")},
        }
    return {
        "PKG-INFO": metadata, "pyproject.toml": b"", "README.pypi.md": b"# E-commerce Eval",
        "LICENSE": b"MIT", ".gitignore": b"runs/\n.env\n",
        "src/commerce_eval/__init__.py": b"",
        "src/commerce_eval/static/index.html": b'<div id="root"></div>',
        "src/commerce_eval/static/assets/app.js": b"// bundled application",
        **{f"examples/{name}": b"{}" for name in ("dataset.jsonl", "tool-contracts.json", "traces.jsonl")},
    }


@pytest.mark.parametrize("kind", ["wheel", "sdist"])
def test_runtime_and_metadata_are_accepted(kind):
    release.validate_members(members(kind), kind, VERSION)


@pytest.mark.parametrize("name", ["../key", "/root/key", "C:/key", ".env", "runs/data.json", "src/.private/key", "state.db", "src/__pycache__/a.pyc"])
def test_private_paths_are_rejected(name):
    with pytest.raises(ValueError):
        release.check_path(name)


@pytest.mark.parametrize("kind", ["wheel", "sdist"])
def test_unknown_payload_is_rejected(kind):
    content = members(kind)
    content["private-report.txt"] = b"not part of a distribution"
    with pytest.raises(ValueError):
        release.validate_members(content, kind, VERSION)


@pytest.mark.parametrize("kind", ["wheel", "sdist"])
def test_missing_frontend_fails(kind):
    content = {name: value for name, value in members(kind).items() if not name.endswith(".js")}
    with pytest.raises(ValueError, match="frontend_bundle_missing"):
        release.validate_members(content, kind, VERSION)


def test_secret_error_does_not_echo_secret():
    content = members("wheel")
    secret = "sk-" + "x" * 40
    content["commerce_eval/unsafe.py"] = secret.encode()
    with pytest.raises(ValueError) as error:
        release.validate_members(content, "wheel", VERSION)
    assert secret not in str(error.value)


def test_missing_demo_fails():
    content = members("wheel")
    del content["commerce_eval/demo_data/traces.jsonl"]
    with pytest.raises(ValueError, match="required_distribution_member_missing"):
        release.validate_members(content, "wheel", VERSION)


def test_version_mismatch_fails():
    with pytest.raises(ValueError, match="release_metadata_mismatch"):
        release.validate_members(members("sdist"), "sdist", "9.9.9")


def test_readme_links_are_absolute():
    text = (ROOT / "README.pypi.md").read_text(encoding="utf-8")
    assert "](docs/" not in text
    assert "](README" not in text
    assert "0.3.0rc2" in text
    assert "not a stable release" in text
