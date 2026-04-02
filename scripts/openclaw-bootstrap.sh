#!/usr/bin/env bash

set -Eeuo pipefail

log() {
  printf '[openclaw-bootstrap] %s\n' "$*"
}

die() {
  printf '[openclaw-bootstrap][ERROR] %s\n' "$*" >&2
  exit 1
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || die "required command not found: $1"
}

sed_escape() {
  printf '%s' "$1" | sed -e 's/[\/&]/\\&/g'
}

load_env_file() {
  local env_file="$1"

  if [[ -z "${env_file}" ]]; then
    return 0
  fi

  if [[ ! -f "${env_file}" ]]; then
    die "env file not found: ${env_file}"
  fi

  log "loading environment from ${env_file}"
  set -a
  # shellcheck disable=SC1090
  source "${env_file}"
  set +a
}

render_config() {
  local template_path="$1"
  local output_path="$2"

  [[ -f "${template_path}" ]] || die "config template not found: ${template_path}"
  mkdir -p "$(dirname "${output_path}")"

  sed \
    -e "s/__OPENCLAW_GATEWAY_BIND__/$(sed_escape "${OPENCLAW_GATEWAY_BIND}")/g" \
    -e "s/__OPENCLAW_GATEWAY_PORT__/$(sed_escape "${OPENCLAW_GATEWAY_PORT}")/g" \
    -e "s#__OPENCLAW_WORKSPACE_PATH__#$(sed_escape "${OPENCLAW_WORKSPACE_PATH}")#g" \
    -e "s/__OPENCLAW_AGENT_ID__/$(sed_escape "${OPENCLAW_AGENT_ID}")/g" \
    "${template_path}" > "${output_path}"
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
DEFAULT_ENV_FILE="${REPO_ROOT}/config/openclaw/.env.local"

if [[ -n "${OPENCLAW_ENV_FILE:-}" ]]; then
  load_env_file "${OPENCLAW_ENV_FILE}"
elif [[ -f "${DEFAULT_ENV_FILE}" ]]; then
  load_env_file "${DEFAULT_ENV_FILE}"
fi

case "$(uname -s)" in
  Darwin|Linux) ;;
  *)
    die "unsupported platform; this bootstrap currently targets macOS first and Linux second"
    ;;
esac

require_command bash
require_command curl
require_command sed

OPENCLAW_INSTALLER_URL="${OPENCLAW_INSTALLER_URL:-https://openclaw.ai/install-cli.sh}"
OPENCLAW_INSTALL_PREFIX="${OPENCLAW_INSTALL_PREFIX:-${HOME}/.openclaw-harness}"
OPENCLAW_VERSION="${OPENCLAW_VERSION:-latest}"
OPENCLAW_STATE_DIR="${OPENCLAW_STATE_DIR:-${HOME}/.openclaw-harness-state}"
OPENCLAW_CONFIG_TEMPLATE="${OPENCLAW_CONFIG_TEMPLATE:-${REPO_ROOT}/config/openclaw/openclaw.template.json5}"
OPENCLAW_CONFIG_PATH="${OPENCLAW_CONFIG_PATH:-${REPO_ROOT}/config/openclaw/openclaw.local.json5}"
OPENCLAW_WORKSPACE_PATH="${OPENCLAW_WORKSPACE_PATH:-${REPO_ROOT}}"
OPENCLAW_GATEWAY_BIND="${OPENCLAW_GATEWAY_BIND:-loopback}"
OPENCLAW_GATEWAY_PORT="${OPENCLAW_GATEWAY_PORT:-18789}"
OPENCLAW_AGENT_ID="${OPENCLAW_AGENT_ID:-harness-local}"

mkdir -p "${OPENCLAW_INSTALL_PREFIX}" "${OPENCLAW_STATE_DIR}" "$(dirname "${OPENCLAW_CONFIG_PATH}")"

log "installing OpenClaw into ${OPENCLAW_INSTALL_PREFIX}"
install_args=(--prefix "${OPENCLAW_INSTALL_PREFIX}" --version "${OPENCLAW_VERSION}" --no-onboard)
curl -fsSL --proto '=https' --tlsv1.2 "${OPENCLAW_INSTALLER_URL}" | bash -s -- "${install_args[@]}"

OPENCLAW_BIN="${OPENCLAW_BIN:-${OPENCLAW_INSTALL_PREFIX}/bin/openclaw}"
[[ -x "${OPENCLAW_BIN}" ]] || die "openclaw binary not found after install: ${OPENCLAW_BIN}"

log "rendering config to ${OPENCLAW_CONFIG_PATH}"
render_config "${OPENCLAW_CONFIG_TEMPLATE}" "${OPENCLAW_CONFIG_PATH}"

export OPENCLAW_CONFIG_PATH
export OPENCLAW_STATE_DIR

log "validating installation"
"${OPENCLAW_BIN}" --version
"${OPENCLAW_BIN}" config file
"${OPENCLAW_BIN}" config validate

cat <<EOF
[openclaw-bootstrap] bootstrap complete
[openclaw-bootstrap] openclaw_bin=${OPENCLAW_BIN}
[openclaw-bootstrap] config_path=${OPENCLAW_CONFIG_PATH}
[openclaw-bootstrap] state_dir=${OPENCLAW_STATE_DIR}
EOF
