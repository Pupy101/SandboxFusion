# Copyright 2024 Bytedance Ltd. and/or its affiliates
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import base64
import os
import re
import shutil
import subprocess
import tempfile
import time
import uuid
from typing import Any, Optional

import structlog

from sandbox.utils.execution import get_tmp_dir

logger = structlog.stdlib.get_logger()

DEFAULT_TTL = 1800
SESSION_DIR = os.path.join(get_tmp_dir(), "sessions")
_sessions: dict[str, dict[str, Any]] = {}


def _ensure_sessions_dir() -> str:
    os.makedirs(SESSION_DIR, exist_ok=True)
    return SESSION_DIR


def _validate_path(path: str) -> bool:
    if ".." in path or len(path) > 256:
        return False
    if not re.match(r"^[a-zA-Z0-9_.\-/]+$", path):
        return False
    return True


def _session_workspace(session_id: str) -> str:
    return os.path.join(SESSION_DIR, session_id, "workspace")


def create_session(
    ttl: int = DEFAULT_TTL,
    image: Optional[str] = None,
    memory: int = 512,
    cpu: float = 1.0,
) -> str:
    session_id = str(uuid.uuid4())
    workspace = os.path.join(SESSION_DIR, session_id, "workspace")
    os.makedirs(workspace, exist_ok=True)
    img = image or "python:3.11-slim"
    mem_limit = f"-m {memory}m" if memory > 0 else ""
    cmd = f"docker run -d --rm --network none {mem_limit} -v {workspace}:/workspace -w /workspace {img} sleep {ttl + 60}"
    proc = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"Failed to create container: {proc.stderr}")
    container_id = proc.stdout.strip()
    _sessions[session_id] = {
        "container_id": container_id,
        "workspace": workspace,
        "last_activity": time.time(),
        "ttl": ttl,
    }
    return session_id


def execute_session(session_id: str, code: str) -> dict[str, Any]:
    if session_id not in _sessions:
        return {"status": "error", "stdout": "", "stderr": "Session not found"}
    s = _sessions[session_id]
    container_id = s["container_id"]
    s["last_activity"] = time.time()
    code_path = os.path.join(s["workspace"], "_cell.py")
    with open(code_path, "w") as f:
        f.write(code)
    proc = subprocess.run(
        f"docker exec {container_id} python /workspace/_cell.py",
        shell=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return {
        "status": "success" if proc.returncode == 0 else "error",
        "stdout": proc.stdout or "",
        "stderr": proc.stderr or "",
    }


def upload_files(session_id: str, files: dict[str, str]) -> list[str]:
    if session_id not in _sessions:
        return []
    s = _sessions[session_id]
    workspace = s["workspace"]
    uploaded: list[str] = []
    for path, content in files.items():
        if not _validate_path(path):
            continue
        fp = os.path.join(workspace, path)
        os.makedirs(os.path.dirname(fp) or ".", exist_ok=True)
        with open(fp, "wb") as f:
            f.write(base64.b64decode(content))
        uploaded.append(path)
    s["last_activity"] = time.time()
    return uploaded


def list_files(session_id: str) -> list[str]:
    if session_id not in _sessions:
        return []
    workspace = _sessions[session_id]["workspace"]
    result: list[str] = []
    for root, _, names in os.walk(workspace):
        for name in names:
            full = os.path.join(root, name)
            rel = os.path.relpath(full, workspace)
            if _validate_path(rel):
                result.append(rel)
    return result


def finish_session(session_id: str) -> bool:
    if session_id not in _sessions:
        return False
    s = _sessions.pop(session_id)
    container_id = s["container_id"]
    subprocess.run(f"docker stop {container_id}", shell=True, capture_output=True)
    try:
        shutil.rmtree(os.path.dirname(s["workspace"]))
    except Exception:
        pass
    return True


def cleanup_expired_sessions() -> int:
    now = time.time()
    expired = [sid for sid, s in _sessions.items() if now - s["last_activity"] > s["ttl"]]
    for sid in expired:
        finish_session(sid)
    return len(expired)
