.PHONY: test lint test-go test-py test-rust lint-go lint-py lint-rust build reproduce paper data release-check dataset

GO_MODULES := controller snapshotter hw/edge-relay
# Python code linted by ruff (config in ruff.toml); harness/ owns the venv.
PY_DIRS := harness cascade baselines analysis hw/bridge-app hw/contention

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

# Compile the technical report from paper/figures/ (run `make reproduce` first).
paper:
	cd paper && typst compile main.typ rootline-v0.1.pdf

# Download the published dataset into data/ and verify its checksums.
data:
	uv run --project harness python -m analysis fetch-data

# Build dist/rootline-v0.1-data for Hugging Face (publishing is manual).
dataset:
	uv run --project harness python -m analysis package-dataset

# Final gate before the release: data complete, results fresh, git clean.
release-check:
	uv run --project harness python -m analysis release-check
