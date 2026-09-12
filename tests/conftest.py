"""Every ordinary pytest run is isolated from machine credentials."""

import os
import pytest


@pytest.fixture(autouse=True)
def isolated_machine_credentials(monkeypatch):
    monkeypatch.setenv("COMMERCE_EVAL_DISABLE_CENTRAL_ENV", "1")
    for name in tuple(os.environ):
        if name.endswith("_API_KEY"):
            monkeypatch.delenv(name, raising=False)
