import os

import pytest

from src.transform.governance import load_hmac_secret, pseudonymise


def test_pseudonymise_is_deterministic(hmac_secret):
    result1 = pseudonymise("EMP001", hmac_secret)
    result2 = pseudonymise("EMP001", hmac_secret)
    assert result1 == result2


def test_pseudonymise_different_inputs_differ(hmac_secret):
    assert pseudonymise("EMP001", hmac_secret) != pseudonymise("EMP002", hmac_secret)


def test_pseudonymise_different_secrets_differ():
    secret_a = b"secret-a"
    secret_b = b"secret-b"
    assert pseudonymise("EMP001", secret_a) != pseudonymise("EMP001", secret_b)


def test_pseudonymise_no_raw_value_in_output(hmac_secret):
    raw = "756.1234.5678.90"
    result = pseudonymise(raw, hmac_secret)
    assert raw not in result


def test_pseudonymise_output_is_16_hex_chars(hmac_secret):
    result = pseudonymise("EMP001", hmac_secret)
    assert len(result) == 16
    assert all(c in "0123456789abcdef" for c in result)


def test_hmac_secret_required(monkeypatch):
    monkeypatch.delenv("PIPELINE_HMAC_SECRET", raising=False)
    with pytest.raises(EnvironmentError):
        load_hmac_secret()


def test_hmac_secret_empty_string_raises(monkeypatch):
    monkeypatch.setenv("PIPELINE_HMAC_SECRET", "")
    with pytest.raises(EnvironmentError):
        load_hmac_secret()


def test_load_hmac_secret_returns_bytes(monkeypatch):
    monkeypatch.setenv("PIPELINE_HMAC_SECRET", "mysecret")
    result = load_hmac_secret()
    assert isinstance(result, bytes)
    assert result == b"mysecret"
