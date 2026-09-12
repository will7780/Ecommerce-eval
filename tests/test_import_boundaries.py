from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_public_core_has_no_product_or_framework_imports() -> None:
    source_roots = [ROOT / "src" / "commerce_eval" / name for name in ("contracts", "core", "packs")]
    forbidden = ("agent" + ".", "lang" + "graph", "lang" + "chain")
    for source_root in source_roots:
        for path in source_root.rglob("*.py"):
            text = path.read_text(encoding="utf-8").lower()
            for token in forbidden:
                assert f"import {token}" not in text, f"{path} imports forbidden dependency {token}"
                assert f"from {token}" not in text, f"{path} imports forbidden dependency {token}"


def test_public_fixtures_do_not_contain_private_product_markers() -> None:
    forbidden = ("te" + "mu", "ao" + "som", "c:" + "\\users\\")
    for root_name in ("src", "examples"):
        for path in (ROOT / root_name).rglob("*"):
            if not path.is_file() or path.suffix.lower() not in {".py", ".json", ".jsonl", ".md", ".txt"}:
                continue
            text = path.read_text(encoding="utf-8").lower()
            assert all(token not in text for token in forbidden), path

