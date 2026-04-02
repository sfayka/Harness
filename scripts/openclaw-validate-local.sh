#!/usr/bin/env bash

set -Eeuo pipefail

log() {
  printf '[openclaw-validate] %s\n' "$*"
}

die() {
  printf '[openclaw-validate][ERROR] %s\n' "$*" >&2
  exit 1
}

load_env_file() {
  local env_file="$1"

  if [[ -z "${env_file}" ]]; then
    return 0
  fi

  if [[ ! -f "${env_file}" ]]; then
    die "env file not found: ${env_file}"
  fi

  set -a
  # shellcheck disable=SC1090
  source "${env_file}"
  set +a
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
DEFAULT_ENV_FILE="${REPO_ROOT}/config/openclaw/.env.local"

if [[ -n "${OPENCLAW_ENV_FILE:-}" ]]; then
  load_env_file "${OPENCLAW_ENV_FILE}"
elif [[ -f "${DEFAULT_ENV_FILE}" ]]; then
  load_env_file "${DEFAULT_ENV_FILE}"
fi

OPENCLAW_INSTALL_PREFIX="${OPENCLAW_INSTALL_PREFIX:-${HOME}/.openclaw-harness}"
OPENCLAW_CONFIG_PATH="${OPENCLAW_CONFIG_PATH:-${REPO_ROOT}/config/openclaw/openclaw.local.json5}"
OPENCLAW_STATE_DIR="${OPENCLAW_STATE_DIR:-${HOME}/.openclaw-harness-state}"
OPENCLAW_BIN="${OPENCLAW_BIN:-${OPENCLAW_INSTALL_PREFIX}/bin/openclaw}"

[[ -x "${OPENCLAW_BIN}" ]] || die "openclaw binary not found: ${OPENCLAW_BIN}"
[[ -f "${OPENCLAW_CONFIG_PATH}" ]] || die "config file not found: ${OPENCLAW_CONFIG_PATH}"

export OPENCLAW_CONFIG_PATH
export OPENCLAW_STATE_DIR

"${OPENCLAW_BIN}" --version
"${OPENCLAW_BIN}" doctor --non-interactive
"${OPENCLAW_BIN}" config file
"${OPENCLAW_BIN}" config validate --json
"${OPENCLAW_BIN}" status

if "${OPENCLAW_BIN}" gateway status >/dev/null 2>&1; then
  "${OPENCLAW_BIN}" gateway status

  if "${OPENCLAW_BIN}" gateway probe >/dev/null 2>&1; then
    "${OPENCLAW_BIN}" health
  else
    log "gateway is configured but unreachable; skipping health check"
  fi
else
  log "gateway is not running; skipping gateway status output and health check"
fi
