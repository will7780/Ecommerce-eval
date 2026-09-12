"""README media preparation is offline and never changes the scoring rules."""
import importlib.util
import json
import socket
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("readme_media", ROOT / "tools/prepare_readme_media.py")
media = importlib.util.module_from_spec(spec)
spec.loader.exec_module(media)


def test_media_is_offline_and_preserves_three_distinct_verdicts(tmp_path, monkeypatch):
    from commerce_eval.providers.credentials import CredentialResolver
    from commerce_eval.storage import Database, Repository

    def deny(*args, **kwargs):
        raise AssertionError("No credential/network access in documentation preparation")

    monkeypatch.setattr(socket, "create_connection", deny)
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(CredentialResolver, "resolve", deny)
    root = tmp_path / "media"
    manifest = media.build_media(root)
    assert manifest["model_executed"] is False
    assert manifest["verdicts"] == {"blocked": "pass", "violation": "fail", "missing-evidence": "error"}
    database = Database(root / "media.db")
    try:
        repo = Repository(database)
        bank = repo.get_dataset("readme-synthetic", "commerce-standard-bank", "0.3.1")
        assert bank["case_count"] == 32
        assert len(repo.list_traces()) == 3
        for label in manifest["verdicts"]:
            trace_id = "readme-a04-" + label
            detail = repo.get_trace(trace_id)
            assert detail["trace"]["tags"]["candidate_evaluation"] == "false"
            assert detail["trace"]["metadata"]["reference_fixture"] is True
            assert detail["trace"]["resource_usage"]["total_tokens"] is None
            evidence = json.loads((root / trace_id / "evidence.json").read_text(encoding="utf-8"))
            assert evidence["collector_id"] == "offline-fixture-not-live"
            assert len(evidence["artifacts"]) == 2
            for artifact in evidence["artifacts"]:
                rows = json.loads((root / trace_id / ("catalog-v" + artifact["version"] + ".json")).read_text(encoding="utf-8"))
                assert rows == artifact["rows"]
        assert repo.get_trace("readme-a04-blocked")["overall_pass"] is True
        assert repo.get_trace("readme-a04-violation")["overall_pass"] is False
        assert repo.get_trace("readme-a04-missing-evidence")["overall_pass"] is False
    finally:
        database.dispose()


def test_existing_destination_is_never_overwritten(tmp_path):
    root = tmp_path / "existing"
    root.mkdir()
    marker = root / "keep.txt"
    marker.write_text("keep", encoding="utf-8")
    with pytest.raises(FileExistsError):
        media.build_media(root)
    assert marker.read_text(encoding="utf-8") == "keep"
    assert not (root / "media.db").exists()


@pytest.mark.parametrize("readme", ["README.md", "README.en.md"])
def test_readme_has_honest_versions_and_entry_points(readme):
    content = (ROOT / readme).read_text(encoding="utf-8")
    for value in ("0.3.0rc2", "0.3.1", "0.1.0", 'id="quickstart"', 'id="example"', 'id="skill"', 'id="docs"'):
        assert value in content
    assert "pip install commerce-agent-eval" not in content
    assert "actions/workflows/ci.yml/badge.svg?branch=main" in content
    assert "img.shields.io/badge/License-MIT-" in content
    assert "img.shields.io/badge/Python-3.10%2B-" in content
    assert "img.shields.io/badge/Status-Alpha-" in content
    assert "shields.io/pypi/" not in content
    assert "shields.io/github/stars/" not in content
    assert "docs/README_MEDIA.md" in content
    assert content.index("banner.svg") < content.index('id="quickstart"')
    assert content.index('id="example"') < content.index("assets/readme/acceptance-")
    for anchor in ("bank", "limits"):
        assert f'id="{anchor}"' in content
    assert content.count("<details>") == content.count("</details>")


def test_readme_banner_is_a_self_contained_brand_asset():
    from xml.etree import ElementTree

    content = (ROOT / "docs/assets/readme/banner.svg").read_text(encoding="utf-8")
    root = ElementTree.fromstring(content)
    assert root.attrib["viewBox"] == "0 0 1600 360"
    allowed = {"svg", "title", "desc", "rect", "path", "g", "text"}
    for element in root.iter():
        assert element.tag.rsplit("}", 1)[-1] in allowed
        assert not any(key.lower().startswith("on") or "href" in key.lower() for key in element.attrib)
    assert "E-commerce Eval" in content
    assert "ISC License" in content
    assert "Lucide Contributors" in content
    assert "url(" not in content
