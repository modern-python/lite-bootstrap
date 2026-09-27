default: install lint test

install:
    uv lock --upgrade
    uv sync --all-extras --frozen --group lint

lint:
    uv run eof-fixer .
    uv run ruff format
    uv run ruff check --fix
    uv run ty check

lint-ci:
    uv run eof-fixer . --check
    uv run ruff format --check
    uv run ruff check --no-fix
    uv run ty check

adr_check_source := "https://raw.githubusercontent.com/modern-python/.github/main/tests/test_adr_citations.py"

# Tracks main on purpose: the shared check is unpinned.
adr-check:
    #!/usr/bin/env sh
    set -eu
    dir="$(mktemp -d .adr-check.XXXXXX)"
    trap 'rm -rf "$dir"' EXIT
    curl -fsSL "{{ adr_check_source }}" -o "$dir/test_adr_citations.py"
    uv run --no-sync pytest --rootdir=. --noconftest -o addopts= "$dir/test_adr_citations.py"

test *args:
    uv run --no-sync pytest {{ args }}

test-ci:
    uv run --no-sync pytest --cov=. --cov-report term-missing --cov-report xml

test-branch:
    @just test --cov=. --cov-branch

# Auth via PyPI Trusted Publishing (OIDC); uv publish auto-detects the CI id-token.
publish:
    rm -rf dist
    uv version $GITHUB_REF_NAME
    uv build
    uv publish

# Strict local docs build (no deploy). Mirrors CI's link/strict checks.
docs-build:
    uvx --with-requirements docs/requirements.txt mkdocs build --strict
