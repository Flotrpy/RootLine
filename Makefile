.PHONY: test lint test-go test-py lint-go lint-py build

GO_MODULES := controller snapshotter

test: test-go test-py

lint: lint-go lint-py

test-go:
	@for m in $(GO_MODULES); do (cd $$m && go test -race ./...) || exit 1; done

lint-go:
	@for m in $(GO_MODULES); do (cd $$m && go vet ./... && golangci-lint run ./...) || exit 1; done

test-py:
	@if [ -f harness/pyproject.toml ]; then cd harness && uv run pytest -q; fi

lint-py:
	@if [ -f harness/pyproject.toml ]; then cd harness && uv run ruff check . && uv run ruff format --check . && uv run pyright; fi

build:
	@mkdir -p bin
	cd controller && go build -o ../bin/rootlinectl ./cmd/rootlinectl
	cd snapshotter && go build -o ../bin/snapshotter ./cmd/snapshotter
