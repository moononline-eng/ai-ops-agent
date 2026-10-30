from agent.collector import collect, fingerprint_for
from tests.conftest import log_line


def exc_entry(exc_type="KeyError", func="get_order", line=70):
    return {
        "level": "ERROR",
        "msg": "unhandled error",
        "user_email": "alice@example.com",
        "exception": {
            "type": exc_type,
            "message": "'discount'",
            "frames": [
                {"file": "starlette/routing.py", "line": 1, "func": "app"},
                {"file": "demo_app/main.py", "line": line, "func": func},
            ],
        },
    }


def test_same_bug_same_fingerprint_even_if_line_moves():
    a = fingerprint_for(exc_entry(line=70))
    b = fingerprint_for(exc_entry(line=75))
    assert a[0] == b[0]
    assert fingerprint_for(exc_entry(exc_type="ValueError"))[0] != a[0]


def test_uses_deepest_app_frame_not_framework_frame():
    _, _, title = fingerprint_for(exc_entry())
    assert "get_order" in title and "demo_app/main.py" in title


def test_info_lines_are_ignored():
    assert fingerprint_for({"level": "INFO", "msg": "request"}) is None


def test_slow_requests_grouped_by_endpoint():
    entry = {"level": "WARNING", "msg": "slow request", "method": "GET", "path": "/search"}
    fp, kind, _ = fingerprint_for(entry)
    assert kind == "slow_request"
    assert fp == fingerprint_for(dict(entry, duration_ms=999))[0]


def test_collect_groups_counts_redacts_and_checkpoints(tmp_path):
    log = tmp_path / "app.jsonl"
    log.write_text(
        log_line(**exc_entry()) * 5
        + "this is not json\n"
        + log_line(**exc_entry(exc_type="ZeroDivisionError", func="stats"))
        + log_line(level="INFO", msg="request")
    )
    groups, offset = collect(log)
    assert [g.count for g in groups] == [5, 1]  # most frequent first, bad line skipped
    assert len(groups[0].samples) == 3  # capped
    assert "alice@example.com" not in str(groups[0].samples)

    # Second run from the checkpoint sees only new lines.
    with log.open("a") as f:
        f.write(log_line(**exc_entry()))
    groups, _ = collect(log, offset)
    assert len(groups) == 1 and groups[0].count == 1


def test_missing_log_file(tmp_path):
    assert collect(tmp_path / "nope.jsonl") == ([], 0)
