# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- One-command installer (`python setup.py`) — replaces the previous multi-step
  setup with an interactive, standard-library-only script.
- Bundled Ollama via Docker Compose profiles, with automatic detection of an
  existing host Ollama (`host.docker.internal`).
- `/recent [n]` and `/config` slash commands.
- Automated test suite and GitHub Actions CI.
- Animated demo GIF and Open Graph social-preview image.
- Ollama generation options (`num_predict` limit and configurable `temperature`).
- Docker healthcheck for the bot container.
- `Makefile` with `make` shortcuts for common tasks.

### Changed

- Bound the Signal API and Ollama to `127.0.0.1` (previously exposed on all
  interfaces).
- Run the bot container as a non-root user (`appuser`).
- Pinned `ollama` to `0.40.11` and upgraded `signal-cli-rest-api` to `0.101`.
- Rewrote the README with badges, table of contents, attribution, and a
  troubleshooting table.
- Graceful shutdown on SIGINT/SIGTERM.
- Ignore group messages (one-to-one chat only).

### Security

- Added `ALLOWED_ADMINS` to gate privileged commands (`/model <name>`,
  `/maxhistory <n>`, `/config`).
- Added per-sender rate limiting (10 messages/minute).
- Added message length caps for prompts and responses.

### Fixed

- Fixed dead-code image handler in `format_for_signal` — image markdown was
  mangled because links were stripped before images.

### Removed

- `run.sh`, `run.ps1`, and `signal-setup.py` (superseded by `setup.py`).

## [0.0.1] - 2026-04-12

### Added

- Initial release: a Signal bot that forwards messages to a local Ollama model
  and returns AI-generated replies, with per-user conversation memory, model
  switching, a sender allowlist, and telemetry mode.
