#!/usr/bin/env bash

set -Eeuo pipefail

EXPECTED_ROOT="/workspace/Harness"
EXPECTED_ORIGIN="https://github.com/sfayka/Harness.git"
PROOF_FILE=".codex-bootstrap-proof"

log() {
  printf '[bootstrap] %s\n' "$*"
}

blocked() {
  printf '[bootstrap][BLOCKED] %s\n' "$*" >&2
  exit 1
}

have_command() {
  command -v "$1" >/dev/null 2>&1
}

run_install_command() {
  if "$@" >/dev/null 2>&1; then
    return 0
  fi

  return 1
}

resolve_python() {
  if have_command python; then
    printf '%s\n' "python"
    return 0
  fi

  if have_command python3; then
    printf '%s\n' "python3"
    return 0
  fi

  return 1
}

resolve_pip() {
  if have_command pip; then
    printf '%s\n' "pip"
    return 0
  fi

  if have_command pip3; then
    printf '%s\n' "pip3"
    return 0
  fi

  return 1
}

install_python_dependencies() {
  local python_bin="$1"
  local pip_bin="${2:-}"

  if [[ -f requirements.txt ]]; then
    if [[ -n "${pip_bin}" ]]; then
      if ! "${pip_bin}" install -q -r requirements.txt >/dev/null 2>&1; then
        log "requirements.txt installation failed; continuing"
      fi
    elif ! "$python_bin" -m pip install -q -r requirements.txt >/dev/null 2>&1; then
      log "requirements.txt installation failed; continuing"
    fi
  fi

  if [[ -f requirements-dev.txt ]]; then
    if [[ -n "${pip_bin}" ]]; then
      if ! "${pip_bin}" install -q -r requirements-dev.txt >/dev/null 2>&1; then
        log "requirements-dev.txt installation failed; continuing"
      fi
    elif ! "$python_bin" -m pip install -q -r requirements-dev.txt >/dev/null 2>&1; then
      log "requirements-dev.txt installation failed; continuing"
    fi
  fi
}

install_node_dependencies() {
  if [[ -f pnpm-lock.yaml ]]; then
    if have_command pnpm; then
      if ! pnpm install --frozen-lockfile --reporter=silent >/dev/null 2>&1; then
        log "pnpm install failed; continuing"
      fi
    else
      log "pnpm-lock.yaml present but pnpm is unavailable; continuing"
    fi
    return 0
  fi

  if [[ -f package-lock.json ]]; then
    if have_command npm; then
      if ! npm ci --silent >/dev/null 2>&1; then
        log "npm ci failed; continuing"
      fi
    else
      log "package-lock.json present but npm is unavailable; continuing"
    fi
    return 0
  fi

  if [[ -f yarn.lock ]]; then
    if have_command yarn; then
      if ! yarn install --frozen-lockfile --silent >/dev/null 2>&1; then
        log "yarn install failed; continuing"
      fi
    else
      log "yarn.lock present but yarn is unavailable; continuing"
    fi
    return 0
  fi

  if [[ -f package.json ]]; then
    if have_command npm; then
      if ! npm install --silent >/dev/null 2>&1; then
        log "npm install failed; continuing"
      fi
    else
      log "package.json present but npm is unavailable; continuing"
    fi
  fi
}

install_gh_cli() {
  if have_command gh; then
    return 0
  fi

  if have_command apt-get; then
    if run_install_command apt-get update; then
      if run_install_command apt-get install -y gh; then
        return 0
      fi
    fi
  fi

  if have_command apk; then
    if run_install_command apk add --no-cache gh; then
      return 0
    fi
  fi

  if have_command brew; then
    if run_install_command brew install gh; then
      return 0
    fi
  fi

  log "gh install skipped or failed"
  return 1
}

authenticate_gh_cli() {
  if ! have_command gh; then
    return 1
  fi

  if gh auth login --with-token >/dev/null 2>&1 <<<"${GH_AUTH}"; then
    return 0
  fi

  log "gh authentication failed; continuing"
  return 1
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

if [[ "${REPO_ROOT}" != "${EXPECTED_ROOT}" ]]; then
  blocked "expected repository root ${EXPECTED_ROOT}, found ${REPO_ROOT}"
fi

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  blocked "current directory is not a git worktree"
fi

if git remote get-url origin >/dev/null 2>&1; then
  origin_fetch_url="$(git remote get-url origin)"
else
  if ! git remote add origin "${EXPECTED_ORIGIN}" >/dev/null 2>&1; then
    blocked "failed to add origin remote"
  fi
  origin_fetch_url="${EXPECTED_ORIGIN}"
fi

origin_push_url="$(git remote get-url --push origin 2>/dev/null || printf '%s' "${origin_fetch_url}")"

if [[ "${origin_fetch_url}" != "${EXPECTED_ORIGIN}" ]]; then
  blocked "origin fetch URL mismatch"
fi

if [[ "${origin_push_url}" != "${EXPECTED_ORIGIN}" ]]; then
  blocked "origin push URL mismatch"
fi

git config --local user.name "Codex"
git config --local user.email "codex@users.noreply.github.com"

if [[ -z "${GH_AUTH:-}" ]]; then
  blocked "GH_AUTH environment variable is required"
fi

python_available=false
python_bin=""
if python_bin="$(resolve_python 2>/dev/null)"; then
  python_available=true
else
  blocked "python is required to configure GitHub authentication"
fi

pip_bin=""
if ! pip_bin="$(resolve_pip 2>/dev/null)"; then
  pip_bin=""
fi

github_extraheader="$("${python_bin}" - <<'PY'
import base64
import os
import sys

token = os.environ.get("GH_AUTH")
if not token:
    sys.exit("GH_AUTH environment variable is required")

encoded = base64.b64encode(f"x-access-token:{token}".encode("utf-8")).decode("ascii")
print(f"AUTHORIZATION: basic {encoded}")
PY
)" || blocked "failed to construct GitHub authentication header"

git config --local --replace-all http.https://github.com/.extraheader "${github_extraheader}"
unset github_extraheader

if ! git fetch origin --prune --quiet >/dev/null 2>&1; then
  blocked "failed to fetch origin"
fi

node_available=false
pnpm_available=false
npm_available=false
gh_available=false
gh_authenticated=false

if have_command node; then
  node_available=true
fi

if have_command pnpm; then
  pnpm_available=true
fi

if have_command npm; then
  npm_available=true
fi

if have_command gh || install_gh_cli; then
  gh_available=true
  if authenticate_gh_cli; then
    gh_authenticated=true
  fi
fi

install_python_dependencies "${python_bin}" "${pip_bin}"
install_node_dependencies

cat > "${PROOF_FILE}" <<EOF
pwd=${REPO_ROOT}
origin_url=${origin_fetch_url}
git_user=$(git config --local user.name)
git_email=$(git config --local user.email)
python_available=${python_available}
node_available=${node_available}
pnpm_available=${pnpm_available}
npm_available=${npm_available}
gh_available=${gh_available}
gh_authenticated=${gh_authenticated}
fetched_origin=true
bootstrap_complete=true
EOF

log "bootstrap complete"
