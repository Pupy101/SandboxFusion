import base64
import shutil

import pytest
from fastapi.testclient import TestClient

from sandbox.server.server import app

client = TestClient(app)

docker_available = shutil.which("docker") is not None
pytestmark = pytest.mark.skipif(not docker_available, reason="Docker not available")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_session(**kwargs) -> str:
    resp = client.post("/sessions", json=kwargs)
    assert resp.status_code == 200, resp.text
    session_id = resp.json()["id"]
    assert session_id
    return session_id


def _finish(session_id: str) -> None:
    client.post(f"/sessions/{session_id}/finish")


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------

def test_session_create_returns_id():
    session_id = _create_session()
    _finish(session_id)


def test_session_finish_returns_finished():
    session_id = _create_session()
    resp = client.post(f"/sessions/{session_id}/finish")
    assert resp.status_code == 200
    assert resp.json()["status"] == "finished"


# ---------------------------------------------------------------------------
# Execute
# ---------------------------------------------------------------------------

def test_session_execute_simple():
    session_id = _create_session()
    try:
        resp = client.post(f"/sessions/{session_id}/execute", json={"code": "print('hello')"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert "hello" in data["stdout"]
    finally:
        _finish(session_id)


def test_session_execute_state_persists():
    """Переменные, определённые в одном вызове, доступны в следующем."""
    session_id = _create_session()
    try:
        r1 = client.post(f"/sessions/{session_id}/execute", json={"code": "x = 42"})
        assert r1.json()["status"] == "success"

        r2 = client.post(f"/sessions/{session_id}/execute", json={"code": "print(x)"})
        assert r2.json()["status"] == "success"
        assert "42" in r2.json()["stdout"]
    finally:
        _finish(session_id)


def test_session_execute_error_code():
    session_id = _create_session()
    try:
        resp = client.post(f"/sessions/{session_id}/execute", json={"code": "raise ValueError('boom')"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "error"
        assert "ValueError" in data["stderr"]
    finally:
        _finish(session_id)


def test_session_execute_stdout_and_stderr_separated():
    session_id = _create_session()
    try:
        code = "import sys; print('out'); sys.stderr.write('err\\n')"
        resp = client.post(f"/sessions/{session_id}/execute", json={"code": code})
        assert resp.status_code == 200
        data = resp.json()
        assert "out" in data["stdout"]
        assert "err" in data["stderr"]
    finally:
        _finish(session_id)


def test_session_execute_not_found():
    resp = client.post("/sessions/nonexistent-id/execute", json={"code": "print(1)"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "error"
    assert "not found" in data["stderr"].lower()


# ---------------------------------------------------------------------------
# Files — upload
# ---------------------------------------------------------------------------

def test_session_upload_file():
    session_id = _create_session()
    try:
        content = base64.b64encode(b"hello from file").decode()
        resp = client.post(f"/sessions/{session_id}/files", json={"files": {"data.txt": content}})
        assert resp.status_code == 200
        assert "data.txt" in resp.json()["uploaded"]
    finally:
        _finish(session_id)


def test_session_upload_file_invalid_path_skipped():
    """Путь с '..' должен быть отклонён — не попасть в uploaded."""
    session_id = _create_session()
    try:
        content = base64.b64encode(b"evil").decode()
        resp = client.post(
            f"/sessions/{session_id}/files",
            json={"files": {"../../etc/passwd": content}},
        )
        assert resp.status_code == 200
        assert "../../etc/passwd" not in resp.json()["uploaded"]
    finally:
        _finish(session_id)


def test_session_upload_file_not_found_session():
    content = base64.b64encode(b"x").decode()
    resp = client.post("/sessions/nonexistent/files", json={"files": {"a.txt": content}})
    assert resp.status_code == 200
    assert resp.json()["uploaded"] == []


# ---------------------------------------------------------------------------
# Files — list
# ---------------------------------------------------------------------------

def test_session_list_files_empty():
    session_id = _create_session()
    try:
        resp = client.get(f"/sessions/{session_id}/files")
        assert resp.status_code == 200
        assert resp.json()["files"] == []
    finally:
        _finish(session_id)


def test_session_list_files_after_upload():
    session_id = _create_session()
    try:
        content = base64.b64encode(b"data").decode()
        client.post(f"/sessions/{session_id}/files", json={"files": {"report.txt": content}})

        resp = client.get(f"/sessions/{session_id}/files")
        assert resp.status_code == 200
        assert "report.txt" in resp.json()["files"]
    finally:
        _finish(session_id)


def test_session_list_files_not_found_session():
    resp = client.get("/sessions/nonexistent/files")
    assert resp.status_code == 200
    assert resp.json()["files"] == []


# ---------------------------------------------------------------------------
# Uploaded file accessible inside session
# ---------------------------------------------------------------------------

def test_session_execute_reads_uploaded_file():
    """Загруженный файл должен быть виден Python-коду в /workspace."""
    session_id = _create_session()
    try:
        content = base64.b64encode(b"secret_value").decode()
        client.post(f"/sessions/{session_id}/files", json={"files": {"secret.txt": content}})

        code = "print(open('/workspace/secret.txt').read())"
        resp = client.post(f"/sessions/{session_id}/execute", json={"code": code})
        assert resp.json()["status"] == "success"
        assert "secret_value" in resp.json()["stdout"]
    finally:
        _finish(session_id)


# ---------------------------------------------------------------------------
# TTL / memory params (smoke — только создание)
# ---------------------------------------------------------------------------

def test_session_create_custom_ttl():
    session_id = _create_session(ttl=60)
    _finish(session_id)


def test_session_create_custom_memory():
    session_id = _create_session(memory=256)
    _finish(session_id)
