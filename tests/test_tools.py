import os

import pytest

from agent.tools import RepoTools, ToolError


def test_read_file_returns_numbered_lines(repo):
    out = RepoTools(repo).read_file("demo_app/main.py")
    assert "   2 |     return sum(orders) / len(orders)" in out


@pytest.mark.parametrize("path", ["../outside.txt", "/etc/passwd", "demo_app/../../x.py", ".env", ".git/config"])
def test_jail_and_denylist(repo, path):
    with pytest.raises(ToolError):
        RepoTools(repo).read_file(path)


def test_symlink_escape_is_blocked(repo, tmp_path_factory):
    outside = tmp_path_factory.mktemp("outside") / "secret.py"
    outside.write_text("TOKEN = 'x'\n")
    os.symlink(outside, repo / "demo_app" / "link.py")
    with pytest.raises(ToolError):
        RepoTools(repo).read_file("demo_app/link.py")


def test_list_files_hides_denied_entries(repo):
    out = RepoTools(repo).list_files(".")
    assert "demo_app/main.py" in out
    assert ".env" not in out and ".git" not in out


def test_search_code(repo):
    tools = RepoTools(repo)
    assert "demo_app/main.py:2" in tools.search_code("len(orders)")
    assert tools.search_code("does-not-exist") == "no matches"
    with pytest.raises(ToolError):
        tools.search_code("")


def test_unknown_tool(repo):
    with pytest.raises(ToolError):
        RepoTools(repo).run("bash", {"cmd": "rm -rf /"})


def test_tool_output_is_redacted(repo):
    (repo / "demo_app" / "cfg.py").write_text("KEY = 'sk-live-abcdefghijklmnopqrstuvwxyz'\n")
    assert "sk-live" not in RepoTools(repo).read_file("demo_app/cfg.py")


def test_raw_logs_are_not_readable(repo):
    (repo / "logs").mkdir()
    (repo / "logs" / "app.md").write_text("alice@example.com\n")
    with pytest.raises(ToolError):
        RepoTools(repo).read_file("logs/app.md")
    assert "logs/" not in RepoTools(repo).list_files(".")
