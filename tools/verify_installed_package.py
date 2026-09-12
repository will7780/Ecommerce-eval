"""Smoke-check the installed package using isolated data and no external calls."""
from __future__ import annotations

import argparse
import asyncio
import importlib.metadata
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import tempfile


class AssetLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        for key, value in attrs:
            if key in {"src", "href"} and value and value.startswith("/assets/"):
                self.links.append(value)


async def verify(version: str) -> dict:
    os.environ["COMMERCE_EVAL_DISABLE_CENTRAL_ENV"] = "1"
    os.environ.pop("COMMERCE_EVAL_API_TOKEN", None)
    import httpx
    import commerce_eval
    from commerce_eval.api import create_app
    from commerce_eval.demo import seed_demo

    if importlib.metadata.version("commerce-agent-eval") != version or commerce_eval.__version__ != version:
        raise ValueError("installed_version_mismatch")
    if "site-packages" not in Path(commerce_eval.__file__).parts:
        raise ValueError("expected_noneditable_installation")
    with tempfile.TemporaryDirectory(prefix="commerce-eval-install-") as directory:
        app = create_app(database_path=Path(directory) / "demo.db")
        try:
            repository = app.state.repository
            first = seed_demo(repository)
            second = seed_demo(repository)
            if first != second:
                raise ValueError("demo_not_idempotent")
            bank = repository.get_dataset("commerce-demo", "commerce-standard-bank", "0.3.1")
            if len(bank["cases"]) != 32:
                raise ValueError("starter_bank_incomplete")
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://localhost") as client:
                health = await client.get("/api/v1/health")
                health.raise_for_status()
                page = await client.get("/")
                page.raise_for_status()
                if 'id="root"' not in page.text:
                    raise ValueError("frontend_missing")
                parser = AssetLinks()
                parser.feed(page.text)
                if not parser.links:
                    raise ValueError("frontend_assets_missing")
                for link in parser.links:
                    asset = await client.get(link)
                    asset.raise_for_status()
                    if not asset.content:
                        raise ValueError("frontend_asset_empty")
                for route in ("/datasets", "/onboarding", "/settings/providers"):
                    (await client.get(route)).raise_for_status()
                for trace_id in first["trace_ids"]:
                    trace = await client.get(f"/api/v1/traces/{trace_id}")
                    trace.raise_for_status()
            return {"status": "passed", "version": version, "bank_cases": 32,
                    "static_assets": len(parser.links), "demo_traces": len(first["trace_ids"]),
                    "external_model_calls": 0, "editable": False}
        finally:
            app.state.database.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True)
    print(json.dumps(asyncio.run(verify(parser.parse_args().version))))


if __name__ == "__main__":
    main()
