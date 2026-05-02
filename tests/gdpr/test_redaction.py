import pytest

from src.transform.governance import redact_free_text


def test_redact_ahv_number():
    text = "My AHV number is 756.1234.5678.90 please advise."
    result, count = redact_free_text(text)
    assert "[REDACTED]" in result
    assert "756.1234.5678.90" not in result
    assert count >= 1


def test_redact_uk_ni():
    text = "NI number: AB123456C is on file."
    result, count = redact_free_text(text)
    assert "[REDACTED]" in result
    assert "AB123456C" not in result
    assert count >= 1


def test_redact_email():
    text = "Please contact me at user@example.com about this."
    result, count = redact_free_text(text)
    assert "[REDACTED]" in result
    assert "user@example.com" not in result
    assert count >= 1


def test_redact_french_ssn():
    # French SSN is 15 digits: 1 (sex) + 2 (year) + 2 (month) + 5 (dept/commune) + 3 (order) + 2 (key)
    text = "French SSN: 185061212345678 is attached."
    result, count = redact_free_text(text)
    assert "[REDACTED]" in result
    assert "185061212345678" not in result
    assert count >= 1


def test_redact_iban():
    text = "Please transfer to CH5604835012345678009."
    result, count = redact_free_text(text)
    assert "[REDACTED]" in result
    assert "CH5604835012345678009" not in result
    assert count >= 1


def test_redact_insurance_reference():
    text = "Card number: INS-2024-88432 needs replacement."
    result, count = redact_free_text(text)
    assert "[REDACTED]" in result
    assert "INS-2024-88432" not in result
    assert count >= 1


def test_redact_bank_account():
    text = "My bank account is Mizuho 1234-5678901."
    result, count = redact_free_text(text)
    assert "[REDACTED]" in result
    assert "1234-5678901" not in result
    assert count >= 1


def test_redact_no_false_positives():
    text = "The employee joined the team in Q3 and is performing well."
    result, count = redact_free_text(text)
    assert result == text
    assert count == 0


def test_redact_multiple_patterns_counted():
    text = "Email user@example.com and NI AB123456C both present."
    result, count = redact_free_text(text)
    assert count >= 2
    assert "user@example.com" not in result
    assert "AB123456C" not in result


def test_redact_non_string_passthrough():
    result, count = redact_free_text(None)
    assert result is None
    assert count == 0


def test_redact_empty_string():
    result, count = redact_free_text("")
    assert result == ""
    assert count == 0
