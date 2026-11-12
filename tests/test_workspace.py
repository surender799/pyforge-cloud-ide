import os
import pytest
from fastapi.testclient import TestClient
from pyforge.workspace import Workspace, Conflict
from pyforge.app import create_app
from pyforge import sandbox


def test_revisions_persist_and_reject_stale(tmp_path):
    w = Workspace(tmp_path)
    d = w.get("main.py")
    w.save("main.py", "print(42)", d["revision"])
    with pytest.raises(Conflict):
        w.save("main.py", "lost update", d["revision"])
    assert Workspace(tmp_path).get("main.py")["content"] == "print(42)"
    assert len(w.history("main.py")) == 2


@pytest.mark.parametrize(
    "path",
    ["../escape", "/etc/passwd", ".git/config", "a/../../x", "a\\b", "a//b", "a/.env"],
)
def test_paths(tmp_path, path):
    with pytest.raises(ValueError):
        Workspace(tmp_path).save(path, "x", 0)


def test_git_commit_and_snapshot(tmp_path):
    w = Workspace(tmp_path)
    assert "main.py" in w.status()["status"]
    state = w.commit("First working program")
    assert "First working program" in state["log"] and state["status"] == ""
    with w.snapshot() as root:
        assert (root / "main.py").exists() and not (root / ".git").exists()


def test_websocket_collaboration_and_conflict(tmp_path):
    with TestClient(create_app(tmp_path)) as c:
        with c.websocket_connect("/ws") as a:
            assert a.receive_json()["type"] == "hello"
            a.receive_json()
            with c.websocket_connect("/ws") as b:
                b.receive_json()
                b.receive_json()
                a.receive_json()
                a.send_json(
                    {
                        "type": "save",
                        "path": "main.py",
                        "content": "print(42)",
                        "revision": 1,
                    }
                )
                assert a.receive_json()["document"]["revision"] == 2
                assert b.receive_json()["document"]["content"] == "print(42)"
                b.send_json(
                    {
                        "type": "save",
                        "path": "main.py",
                        "content": "stale",
                        "revision": 1,
                    }
                )
                assert b.receive_json()["type"] == "conflict"


def test_api_and_sandbox_configuration(tmp_path, monkeypatch):
    monkeypatch.setattr(sandbox.shutil, "which", lambda name: "/usr/bin/docker")
    with TestClient(create_app(tmp_path)) as c:
        assert c.get("/").status_code == 200
        assert (
            c.post(
                "/api/files", json={"path": "a.py", "content": "print(7)"}
            ).status_code
            == 201
        )
        assert c.get("/api/file", params={"path": "../x"}).status_code == 400
    args = sandbox.command(tmp_path, "test", ["python", "main.py"])
    assert "--read-only" in args and "none" in args and "65534:65534" in args


@pytest.mark.skipif(
    os.getenv("RUN_DOCKER_TESTS") != "1",
    reason="Set RUN_DOCKER_TESTS=1 with Docker and the Python image available",
)
def test_real_container(tmp_path):
    w = Workspace(tmp_path)
    with w.snapshot() as root:
        result = sandbox.run(root, ["python", "main.py"])
        assert result["exit_code"] == 0 and "Hello from PyForge" in result["output"]
