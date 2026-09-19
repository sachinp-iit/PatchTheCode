from patchthecode.mcp.redaction import Redactor, redact_text


def test_redact_text_secret_patterns():
    text = 'Authorization: Bearer abc123 password=hunter2 https://u:p@example.com/x'
    out = redact_text(text)
    assert "abc123" not in out
    assert "hunter2" not in out
    assert "u:p@example.com" not in out
    assert "[REDACTED]" in out


def test_redactor_nested_payload():
    payload = {
        "message": "error",
        "headers": {"Authorization": "Bearer tok", "X-Custom": "ok"},
        "nested": {"token": "sekrit", "keep": "value"},
        "list": [{"api_key": "abc"}, {"name": "alice"}],
    }
    redactor = Redactor(field_globs=["token", "api_key", "authorization"])
    out = redactor.redact(payload)
    assert out["headers"]["Authorization"] == "[REDACTED]"
    assert out["nested"]["token"] == "[REDACTED]"
    assert out["nested"]["keep"] == "value"
    assert out["list"][0]["api_key"] == "[REDACTED]"
    assert out["list"][1]["name"] == "alice"


def test_redactor_no_fields_configured_still_masks_known_patterns():
    payload = {"raw": "password: foo", "untouched": "value"}
    out = Redactor([]).redact(payload)
    assert "[REDACTED]" in out["raw"]
    assert out["untouched"] == "value"