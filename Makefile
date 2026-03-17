HOST ?= 0.0.0.0
PORT ?= 8080
TEST_NP ?= 4
run:
	uv run uvicorn sandbox.server.server:app --reload --host $(HOST) --port $(PORT)

run-online:
	uv run uvicorn sandbox.server.server:app --host $(HOST) --port $(PORT)

build-server-image:
	docker build . -f scripts/Dockerfile.server -t sandbox:server

test:
	uv run pytest -m "not cuda and not datalake and not dp_eval and not lean" -n $(TEST_NP)

test-cuda:
	uv run pytest -m cuda

test-minor:
	uv run pytest -m minor

test-verilog:
	uv run pytest -m verilog

test-verilog-pdb:
	uv run pytest -m verilog --pdb --capture=no

test-online:
	ONLINE_TEST=1 uv run pytest

test-case:
	uv run pytest -s -vv -k $(CASE)

format:
	pycln --config pyproject.toml
	isort sandbox/*
	yapf -ir sandbox/*

format-client:
	mv scripts/client/pyproject.toml scripts/faas/pyproject.toml && yapf -ir scripts/client/* && mv scripts/faas/pyproject.toml scripts/client/pyproject.toml

# mypy --explicit-package-bases sandbox
check:
	pycln --config pyproject.toml --check
	yapf --diff --recursive sandbox/*
	make test
