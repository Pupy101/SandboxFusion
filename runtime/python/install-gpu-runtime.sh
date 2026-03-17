#!/bin/bash
set -o errexit

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Install CPU runtime first (creates .venv with Python 3.11 and base packages)
bash ./install-python-runtime.sh

# Activate venv
source .venv/bin/activate

# Install PyTorch with CUDA
bash ./install-pytorch.sh 2.2.1 12.1.0

# Pin numpy for GPU compatibility
uv pip install "numpy<2.0.0"

uv cache clean
