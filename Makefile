.PHONY: test lint test-go test-py test-rust lint-go lint-py lint-rust build reproduce

GO_MODULES := controller snapshotter hw/edge-relay
# Python code linted by ruff (config in ruff.toml); harness/ owns the venv.
PY_DIRS := harness cascade baselines analysis

test: test-go test-py test-rust

lint: lint-go lint-py lint-rust

test-go:
	@for m in $(GO_MODULES); do (cd $$m && go test -race ./...) || exit 1; done

lint-go:
	@for m in $(GO_MODULES); do (cd $$m && go vet ./... && golangci-lint run ./...) || exit 1; done

test-rust:
	cd replay && cargo test -q

lint-rust:
	cd replay && cargo fmt --check && cargo clippy -q --all-targets -- -D warnings

test-py:
	@cd harness && uv run pytest -q

lint-py:
	@uv run --project harness ruff check $(PY_DIRS) && uv run --project harness ruff format --check $(PY_DIRS)
	@cd harness && uv run pyright

build:
	@mkdir -p bin
	cd controller && go build -o ../bin/rootlinectl ./cmd/rootlinectl
	cd snapshotter && go build -o ../bin/snapshotter ./cmd/snapshotter
	cd replay && cargo build --release -q && cp target/release/rootline ../bin/rootline
	cd hw/edge-relay && GOOS=linux GOARCH=arm64 CGO_ENABLED=0 go build -trimpath -o ../../bin/edge-relay-arm64 .

# Regenerate every table and figure in paper/figures/ from data/ (offline).
reproduce:
	uv run --project harness python -m analysis reproduce
