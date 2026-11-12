# Contributing

Create a Python virtual environment and install with python -m pip install -e '.[dev]'. Run python -m pytest -q from the repository root. Keep behavior changes accompanied by tests that exercise failure cases and persistence boundaries where relevant.

The core lives in pyforge/. Static UI files are served directly, with no frontend build step. Keep the README's scope and limits accurate when adding features. Never include .data, .env, credentials, or user repositories in a commit.
