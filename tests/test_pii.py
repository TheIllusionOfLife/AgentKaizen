"""Tests for _pii local PII redaction module."""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from agentkaizen._pii import configure_pii_redaction, redact_pii_local


def _enable_redaction(fields=None):
    configure_pii_redaction(enabled=True, fields=fields)


def _disable_redaction():
    configure_pii_redaction(enabled=False)


def test_configure_sets_state():
    configure_pii_redaction(enabled=True, fields=["prompt", "output"])
    # Verify through redaction behavior
    result = redact_pii_local({"prompt": "user@example.com", "other": "user@example.com"})
    assert "[EMAIL_REDACTED]" in result["prompt"]
    assert result["other"] == "user@example.com"
    _disable_redaction()


def test_disabled_returns_unchanged():
    _disable_redaction()
    value = {"prompt": "user@example.com"}
    assert redact_pii_local(value) == value


def test_redacts_emails():
    _enable_redaction()
    result = redact_pii_local("Contact user@example.com for info")
    assert "user@example.com" not in result
    assert "[EMAIL_REDACTED]" in result
    _disable_redaction()


def test_redacts_phone_numbers():
    _enable_redaction()
    result = redact_pii_local("Call 555-123-4567 or 5551234567")
    assert "555-123-4567" not in result
    assert "[PHONE_REDACTED]" in result
    _disable_redaction()


def test_redacts_ssn():
    _enable_redaction()
    result = redact_pii_local("SSN: 123-45-6789")
    assert "123-45-6789" not in result
    assert "[SSN_REDACTED]" in result
    _disable_redaction()


def test_redacts_credit_cards():
    _enable_redaction()
    result = redact_pii_local("Card: 4111 1111 1111 1111")
    assert "4111 1111 1111 1111" not in result
    assert "[CARD_REDACTED]" in result
    _disable_redaction()


def test_redacts_api_keys():
    _enable_redaction()
    result = redact_pii_local("sk-1234567890abcdefghijklmn")
    assert "sk-1234567890abcdefghijklmn" not in result
    assert "[API_KEY_REDACTED]" in result
    _disable_redaction()


def test_redacts_bearer_tokens():
    _enable_redaction()
    result = redact_pii_local("bearer = abc123secret")
    assert "abc123secret" not in result
    assert "[SECRET_REDACTED]" in result
    _disable_redaction()


def test_recursive_dict_traversal():
    _enable_redaction(fields=["prompt", "nested"])
    value = {
        "prompt": "email: test@test.com",
        "nested": {"deep": "token = secret123"},
        "safe": "test@test.com",
    }
    result = redact_pii_local(value)
    assert "[EMAIL_REDACTED]" in result["prompt"]
    assert "[SECRET_REDACTED]" in result["nested"]["deep"]
    assert result["safe"] == "test@test.com"
    _disable_redaction()


def test_handles_empty_dict():
    _enable_redaction()
    assert redact_pii_local({}) == {}
    _disable_redaction()


def test_handles_none_values_in_dict():
    _enable_redaction()
    result = redact_pii_local({"key": None})
    assert result == {"key": None}
    _disable_redaction()


def test_handles_list_values():
    _enable_redaction(fields=["items"])
    result = redact_pii_local({"items": ["user@example.com", "normal"]})
    assert "[EMAIL_REDACTED]" in result["items"][0]
    assert result["items"][1] == "normal"
    _disable_redaction()


def test_string_input():
    _enable_redaction()
    result = redact_pii_local("user@example.com")
    assert "[EMAIL_REDACTED]" in result
    _disable_redaction()


def test_no_fields_configured_redacts_all_string_fields():
    """When no specific fields are configured, all string fields are redacted."""
    configure_pii_redaction(enabled=True, fields=[])
    result = redact_pii_local({"any_field": "user@example.com"})
    assert "[EMAIL_REDACTED]" in result["any_field"]
    _disable_redaction()
