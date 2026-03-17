#!/bin/bash
set -o errexit

USE_OFFICIAL_SOURCE=0
for arg in "$@"
do
    if [ "$arg" = "us" ]; then
        USE_OFFICIAL_SOURCE=1
    fi
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Install uv if not present
if ! command -v uv &> /dev/null; then
    pip install uv
fi

# Create venv with Python 3.11 (fixes contourpy and other packages requiring 3.11+)
uv venv --python 3.11 .venv
source .venv/bin/activate

# Install packages
if [ $USE_OFFICIAL_SOURCE -eq 0 ]; then
    uv pip install --index-url https://mirrors.aliyun.com/pypi/simple/ -r ./requirements.txt
else
    uv pip install -r ./requirements.txt
fi

# for NaturalCodeBench python problem 29
python -c "import nltk; nltk.download('punkt')"

# for CIBench nltk problems
python -c "import nltk; nltk.download('stopwords')"

uv cache clean
