"""Publication copies approved source, never machine records or credentials."""
import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("public_export", Path(__file__).resolve().parents[1] / "tools/export_public_repo.py")
exporter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(exporter)


@pytest.mark.parametrize("name", [
    ".env", "runs/private.json", "runs/data.db", ".git/config", "web/node_modules/file.js",
    "docs/design/CURSOR_V030_REAL_MODEL_TEST_REPORT.md", "docs/assets/run-detail.png",
    "web/vite.config.js", "web/tsconfig.app.tsbuildinfo", "private-product/runtime.py",
])
def test_private_and_generated_files_are_excluded(name):
    assert not exporter.is_public(Path(name))


@pytest.mark.parametrize("name", [
    "README.md", ".env.example", ".github/workflows/ci.yml", "src/commerce_eval/static/index.html",
    "web/src/App.tsx", "skills/ecommerce-eval-onboarding/agents/openai.yaml",
    "skills/ecommerce-eval-onboarding/assets/bundle-example/importable/dataset.json",
    "docs/design/PUBLIC_ARCHITECTURE.md", "docs/assets/readme/acceptance-zh.png",
    "docs/assets/readme/banner.svg",
])
def test_public_delivery_is_preserved(name):
    assert exporter.is_public(Path(name))


def test_existing_destination_is_unchanged(tmp_path):
    marker = tmp_path / "keep"
    marker.write_text("unchanged")
    with pytest.raises(FileExistsError):
        exporter.export_public(tmp_path, tmp_path)
    assert marker.read_text() == "unchanged"


def test_secret_report_never_contains_the_value():
    secret = "sk-" + "a" * 40
    with pytest.raises(ValueError) as error:
        exporter.audit_file(Path("README.md"), secret.encode())
    assert secret not in str(error.value)


def test_credential_example_must_be_empty():
    with pytest.raises(ValueError, match="nonempty_credential"):
        exporter.audit_file(Path(".env.example"), b"PROVIDER_API_KEY=not-a-real-key")


def test_incomplete_source_produces_no_export(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    destination = tmp_path / "public"
    with pytest.raises(ValueError, match="incomplete_public_source"):
        exporter.export_public(source, destination)
    assert not destination.exists()
