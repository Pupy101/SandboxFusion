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

import os
import traceback
from enum import Enum
from typing import Dict, List, Optional, Tuple

import structlog
from fastapi import APIRouter
from pydantic import BaseModel, Field

from sandbox.runners import (
    CODE_RUNNERS,
    CellRunResult,
    CodeRunArgs,
    CodeRunResult,
    CommandRunResult,
    CommandRunStatus,
    Language,
    RunJupyterRequest,
    run_jupyter,
)
from sandbox.runners.docker_runner import run_code_in_docker
from sandbox.server.sessions import (
    create_session,
    execute_session,
    finish_session,
    list_files,
    upload_files,
)

sandbox_router = APIRouter()
logger = structlog.stdlib.get_logger()


class RunCodeRequest(BaseModel):
    compile_timeout: float = Field(10, description='compile timeout for compiled languages')
    run_timeout: float = Field(10, description='code run timeout')
    memory_limit_MB: int = Field(-1, description='maximum memory allowed in megabytes')
    code: str = Field(..., examples=['print("hello")'], description='the code to run')
    stdin: Optional[str] = Field(None, examples=[''], description='optional string to pass into stdin')
    language: Language = Field(..., examples=['python'], description='the language or execution mode to run the code')
    files: Dict[str, Optional[str]] = Field({}, description='a dict from file path to base64 encoded file content')
    fetch_files: List[str] = Field([], description='a list of file paths to fetch after code execution')
    image: Optional[str] = Field(None, description='optional custom docker image for execution')


class RunStatus(str, Enum):
    # all command finished successfully
    Success = 'Success'
    # one of the process has non-zero return code
    Failed = 'Failed'
    # error on sandbox side
    SandboxError = 'SandboxError'


class RunCodeResponse(BaseModel):
    status: RunStatus
    message: str
    compile_result: Optional[CommandRunResult] = None
    run_result: Optional[CommandRunResult] = None
    executor_pod_name: Optional[str] = None
    files: Dict[str, str] = {}


class RunJupyterResponse(BaseModel):
    status: RunStatus
    message: str
    driver: Optional[CommandRunResult] = None
    cells: List[CellRunResult] = []
    executor_pod_name: Optional[str] = None
    files: Dict[str, str] = {}


def parse_run_status(result: CodeRunResult) -> Tuple[RunStatus, str]:
    outcomes = []
    retcodes = []
    err_msgs = []
    if result.compile_result is not None:
        outcomes.append(result.compile_result.status)
        err_msgs.append(result.compile_result.stderr or '')
        if result.compile_result.return_code is not None:
            retcodes.append(result.compile_result.return_code)
    if result.run_result is not None:
        outcomes.append(result.run_result.status)
        err_msgs.append(result.run_result.stderr or '')
        if result.run_result.return_code is not None:
            retcodes.append(result.run_result.return_code)

    for o, m in zip(outcomes, err_msgs):
        if o == CommandRunStatus.Error:
            return RunStatus.SandboxError, m
    if any([o == CommandRunStatus.TimeLimitExceeded for o in outcomes]):
        return RunStatus.Failed, ''
    if any([r != 0 for r in retcodes]):
        return RunStatus.Failed, ''
    # no error, no tle and no non-zero return codes -> success
    return RunStatus.Success, ''


@sandbox_router.get("/health")
async def health():
    return {"status": "ok"}


@sandbox_router.post("/run_code", response_model=RunCodeResponse, tags=['sandbox'])
async def run_code(request: RunCodeRequest):
    resp = RunCodeResponse(status=RunStatus.Success, message='', executor_pod_name=os.environ.get('MY_POD_NAME'))
    try:
        logger.debug(
            f'start processing {request.language} request with code ```\n{request.code[:100]}\n``` and files {list(request.files.keys())}...(memory_limit: {request.memory_limit_MB}MB)'
        )
        args = CodeRunArgs(**request.model_dump(exclude={'language'}))
        if request.image:
            result = await run_code_in_docker(args, request.language)
        else:
            result = await CODE_RUNNERS[request.language](args)

        resp.compile_result = result.compile_result
        resp.run_result = result.run_result
        resp.files = result.files
        resp.status, message = parse_run_status(result)
        if resp.status == RunStatus.SandboxError:
            resp.message = message
    except Exception as e:
        message = f'exception on running code {request.code}: {e} {traceback.print_tb(e.__traceback__)}'
        logger.warning(message)
        resp.message = message
        resp.status = RunStatus.SandboxError

    return resp


class SessionCreateRequest(BaseModel):
    ttl: int = Field(1800, description='seconds of inactivity before auto-finish')
    image: Optional[str] = Field(None, description='docker image for session')
    memory: int = Field(512, description='memory limit MB')
    cpu: float = Field(1.0, description='CPU limit')


class SessionExecuteRequest(BaseModel):
    code: str = Field(..., description='code to execute')


class SessionFilesRequest(BaseModel):
    files: Dict[str, str] = Field(..., description='path -> base64 content')


@sandbox_router.post("/sessions")
async def session_create(req: SessionCreateRequest):
    session_id = create_session(ttl=req.ttl, image=req.image, memory=req.memory, cpu=req.cpu)
    return {"id": session_id}


@sandbox_router.post("/sessions/{session_id}/execute")
async def session_execute(session_id: str, req: SessionExecuteRequest):
    return execute_session(session_id, req.code)


@sandbox_router.post("/sessions/{session_id}/files")
async def session_upload_files(session_id: str, req: SessionFilesRequest):
    uploaded = upload_files(session_id, req.files)
    return {"uploaded": uploaded}


@sandbox_router.get("/sessions/{session_id}/files")
async def session_list_files(session_id: str):
    files = list_files(session_id)
    return {"files": files}


@sandbox_router.post("/sessions/{session_id}/finish")
async def session_finish(session_id: str):
    finish_session(session_id)
    return {"status": "finished"}


@sandbox_router.post("/run_jupyter", name='Run Code in Jupyter', response_model=RunJupyterResponse, tags=['sandbox'])
async def run_jupyter_handler(request: RunJupyterRequest):
    resp = RunJupyterResponse(status=RunStatus.Success, message='', executor_pod_name=os.environ.get('MY_POD_NAME'))
    code_repr = "\n".join(request.cells)[:100]
    try:
        logger.debug(
            f'start processing jupyter request with code ```\n{code_repr}\n``` and files {list(request.files.keys())}...'
        )
        result = await run_jupyter(request)
        resp.driver = result.driver
        if result.status != CommandRunStatus.Finished:
            resp.status = RunStatus.Failed
        else:
            resp.status = RunStatus.Success
            resp.cells = result.cells
            resp.files = result.files
    except Exception as e:
        message = f'exception on running jupyter {code_repr}: {e} {traceback.print_tb(e.__traceback__)}'
        logger.warning(message)
        resp.message = message
        resp.status = RunStatus.SandboxError

    return resp
