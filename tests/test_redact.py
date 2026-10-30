from agent.redact import redact, redact_obj


def test_redacts_api_keys_and_tokens():
    text = "key sk-ant-api03-abcdefghijklmnop and ghp_abcdefghijklmnop1234 and AKIAABCDEFGHIJKLMNOP"
    out = redact(text)
    assert "sk-ant" not in out
    assert "ghp_" not in out
    assert "AKIA" not in out


def test_redacts_pii():
    out = redact("user alice@example.com from 10.0.0.12 paid with 4111 1111 1111 1111")
    assert "alice@example.com" not in out
    assert "10.0.0.12" not in out
    assert "4111" not in out


def test_redacts_secret_key_values_and_headers():
    out = redact("password=hunter2 Authorization: Bearer abc.def token: xyz")
    assert "hunter2" not in out
    assert "abc.def" not in out
    assert "xyz" not in out
    assert "password=[REDACTED_SECRET_KV]" in out


def test_redacts_nested_structures():
    obj = {"msg": "hi bob@example.com", "list": [{"k": "sk-abcdefghijklmnop"}], "n": 3}
    out = redact_obj(obj)
    assert "bob@example.com" not in str(out)
    assert "sk-abc" not in str(out)
    assert out["n"] == 3


def test_leaves_normal_text_alone():
    assert redact("ZeroDivisionError: division by zero") == "ZeroDivisionError: division by zero"


def test_values_under_sensitive_keys_are_dropped():
    entry = {"headers": {"Authorization": "Bearer abc123", "X-Api-Key": "k1"}, "password": "hunter2", "path": "/x"}
    out = redact_obj(entry)
    assert "abc123" not in str(out) and "k1" not in str(out) and "hunter2" not in str(out)
    assert out["path"] == "/x"
