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

import asyncio
import base64
import os
import tempfile
from typing import Dict, Optional

import structlog

from sandbox.runners.base import restore_files
from sandbox.runners.types import CodeRunArgs, CodeRunResult, CommandRunResult, CommandRunStatus
from sandbox.utils.execution import get_tmp_dir

logger = structlog.stdlib.get_logger()

LANG_TO_CMD: Dict[str, str] = {
    'python': 'python',
    'nodejs': 'node',
    'bash': 'bash',
    'cpp': 'g++ -std=c++17 -x c++ - -o /tmp/out && /tmp/out',
    'go': 'go run',
    'rust': 'rustc - -o /tmp/out && /tmp/out',
    'java': 'java',
    'php': 'php',
    'csharp': 'dotnet',
    'ruby': 'ruby',
    'perl': 'perl',
    'lua': 'lua',
    'R': 'Rscript',
    'julia': 'julia',
}


def _get_run_cmd(lang: str, code_path: str) -> str:
    if lang == 'python':
        return f'python {code_path}'
    if lang == 'nodejs':
        return f'node {code_path}'
    if lang == 'bash':
        return f'bash {code_path}'
    if lang in LANG_TO_CMD:
        return f'{LANG_TO_CMD[lang]} {code_path}'
    return f'python {code_path}'


async def run_code_in_docker(args: CodeRunArgs, lang: str) -> CodeRunResult:
    if not args.image:
        raise ValueError('image is required for docker runner')
    ext = '.py' if lang == 'python' else '.js' if lang == 'nodejs' else '.sh' if lang == 'bash' else '.py'
    with tempfile.TemporaryDirectory(dir=get_tmp_dir(), ignore_cleanup_errors=True) as tmp_dir:
        restore_files(tmp_dir, args.files)
        code_path = os.path.join(tmp_dir, f'main{ext}')
        with open(code_path, 'w') as f:
            f.write(args.code)
        run_cmd = _get_run_cmd(lang, f'/workspace/main{ext}')
        script_path = os.path.join(tmp_dir, 'run.sh')
        with open(script_path, 'w') as f:
            f.write(f'#!/bin/bash\n{run_cmd}\n')
        os.chmod(script_path, 0o755)
        mem_limit = f'-m {args.memory_limit_MB}m' if args.memory_limit_MB > 0 else ''
        docker_cmd = (
            f'docker run --rm --network none {mem_limit} '
            f'-v {tmp_dir}:/workspace -w /workspace {args.image} /workspace/run.sh'
        )
        proc = await asyncio.create_subprocess_shell(
            docker_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            stdin=asyncio.subprocess.PIPE,
        )
        if args.stdin and proc.stdin:
            proc.stdin.write(args.stdin.encode())
            proc.stdin.close()
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=args.run_timeout + 10,
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return CodeRunResult(
                run_result=CommandRunResult(
                    status=CommandRunStatus.TimeLimitExceeded,
                    stderr='Execution timeout',
                )
            )
        status = CommandRunStatus.TimeLimitExceeded if proc.returncode == 137 else (
            CommandRunStatus.Finished if proc.returncode == 0 else CommandRunStatus.Error
        )
        files: Dict[str, str] = {}
        for f in args.fetch_files:
            fp = os.path.join(tmp_dir, f)
            if os.path.isfile(fp):
                with open(fp, 'rb') as fd:
                    files[f] = base64.b64encode(fd.read()).decode()
        return CodeRunResult(
            run_result=CommandRunResult(
                status=status,
                return_code=proc.returncode if proc.returncode is not None else -1,
                stdout=stdout.decode(errors='replace') if stdout else None,
                stderr=stderr.decode(errors='replace') if stderr else None,
            ),
            files=files,
        )
