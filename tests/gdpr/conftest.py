import os

import pytest


@pytest.fixture
def hmac_secret(monkeypatch):
    monkeypatch.setenv("PIPELINE_HMAC_SECRET", "test-secret-key-for-unit-tests")
    return b"test-secret-key-for-unit-tests"


@pytest.fixture
def different_hmac_secret(monkeypatch):
    monkeypatch.setenv("PIPELINE_HMAC_SECRET", "different-secret-key-xyz")
    return b"different-secret-key-xyz"
