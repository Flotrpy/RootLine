.PHONY: test lint test-go test-py lint-go lint-py build

GO_MODULES := controller snapshotter
# Python code linted by ruff (config in ruff.toml); harness/ owns the venv.
PY_DIRS := harness cascade baselines analysis

test: test-go test-py

lint: lint-go lint-py

test-go:
	@for m in $(GO_MODULES); do (cd $$m && go test -race ./...) || exit 1; done

lint-go:
	@for m in $(GO_MODULES); do (cd $$m && go vet ./... && golangci-lint run ./...) || exit 1; done

test-py:
	@cd harness && uv run pytest -q

lint-py:
	@uv run --project harness ruff check $(PY_DIRS) && uv run --project harness ruff format --check $(PY_DIRS)
	@cd harness && uv run pyright

build:
	@mkdir -p bin
	cd controller && go build -o ../bin/rootlinectl ./cmd/rootlinectl
	cd snapshotter && go build -o ../bin/snapshotter ./cmd/snapshotter
