#!/bin/bash
set -o errexit

# CPU-only: same as install-python-runtime.sh (--index-url ensures PyPI/mirror, no CUDA wheels)
bash "$(dirname "${BASH_SOURCE[0]}")/install-python-runtime.sh" "$@"
