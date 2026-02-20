#!/usr/bin/env bash
# mailflow-checker - Debian LXC install/update/uninstall script for Proxmox VE environments
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/fabianpetri/mailflow-checker/main/scripts/install_mailflow_checker.sh | bash -s -- install
#   curl -fsSL https://raw.githubusercontent.com/fabianpetri/mailflow-checker/main/scripts/install_mailflow_checker.sh | bash -s -- update
#   curl -fsSL https://raw.githubusercontent.com/fabianpetri/mailflow-checker/main/scripts/install_mailflow_checker.sh | bash -s -- uninstall
#
# Options/Env:
#   E2E_REPO_URL   Git repository URL (default: current repo when running locally; otherwise must be provided)
#   E2E_BRANCH     Git branch to checkout (default: main)
#   E2E_INTERVAL   systemd timer interval (default: 5m), examples: 1m, 2m, 10m
#   E2E_USER       System user to run the service (default: mailflowchecker)
#
# This script installs:
#   - /opt/mailflow-checker (git clone of repo)
#   - Python venv and requirements
#   - /etc/mailflow-checker/config.yml (created if absent)
#   - systemd service + timer (mailflow-checker.service / .timer)
#
# Idempotent: safe to re-run install and update.
set -euo pipefail

APP_NAME="mailflow-checker"
APP_USER="${E2E_USER:-mailflowchecker}"
APP_DIR="/opt/${APP_NAME}"
VENV_DIR="${APP_DIR}/venv"
CONF_DIR="/etc/${APP_NAME}"
CONF_FILE="${CONF_DIR}/config.yml"
SERVICE_FILE="/etc/systemd/system/${APP_NAME}.service"
TIMER_FILE="/etc/systemd/system/${APP_NAME}.timer"
REPO_URL="${E2E_REPO_URL:-https://github.com/fabianpetri/mailflow-checker.git}"
BRANCH="${E2E_BRANCH:-main}"
INTERVAL="${E2E_INTERVAL:-5m}"

log() { echo -e "[${APP_NAME}] $*"; }
log_warn() { echo -e "[${APP_NAME}] WARNING: $*"; }
log_err() { echo -e "[${APP_NAME}] ERROR: $*" 1>&2; }

require_root() {
  if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
    log_err "Please run as root (sudo)."
    exit 1
  fi
}

ensure_deps() {
  log "Installing OS dependencies (apt update + python3, venv, pip, git)..."
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -y
  apt-get install -y --no-install-recommends \
    ca-certificates curl git python3 python3-venv python3-pip systemd
}

ensure_user() {
  if ! id -u "${APP_USER}" >/dev/null 2>&1; then
    log "Creating system user ${APP_USER}..."
    useradd --system --home "${APP_DIR}" --shell /usr/sbin/nologin "${APP_USER}"
  fi
}

clone_or_update_repo() {
  if [[ -d "${APP_DIR}/.git" ]]; then
    log "Repository already exists. Updating..."
    git -C "${APP_DIR}" fetch --all --prune
    git -C "${APP_DIR}" reset --hard "origin/${BRANCH}"
  else
    if [[ -z "${REPO_URL}" ]]; then
      # If running from a local checkout, copy files; else require REPO_URL
      if [[ -d .git ]]; then
        log "Copying current repository to ${APP_DIR}..."
        mkdir -p "${APP_DIR}"
        rsync -a --delete --exclude ".git" ./ "${APP_DIR}/"
      else
        log_err "E2E_REPO_URL not provided and current dir is not a git repo. Set E2E_REPO_URL to your GitHub repo."
        exit 1
      fi
    else
      log "Cloning ${REPO_URL} (branch: ${BRANCH}) to ${APP_DIR}..."
      git clone --branch "${BRANCH}" --depth 1 "${REPO_URL}" "${APP_DIR}"
    fi
  fi
}

setup_venv() {
  log "Preparing Python venv..."
  python3 -m venv "${VENV_DIR}"
  # shellcheck source=/dev/null
  source "${VENV_DIR}/bin/activate"
  pip install --upgrade pip wheel setuptools
  if [[ -f "${APP_DIR}/requirements.txt" ]]; then
    pip install -r "${APP_DIR}/requirements.txt"
  fi
  deactivate || true
}

install_config() {
  log "Ensuring config directory at ${CONF_DIR}..."
  mkdir -p "${CONF_DIR}"
  chown -R "${APP_USER}:${APP_USER}" "${CONF_DIR}"
  chmod 750 "${CONF_DIR}"
  if [[ ! -f "${CONF_FILE}" ]]; then
    if [[ -f "${APP_DIR}/config.example.yml" ]]; then
      log "Creating initial ${CONF_FILE} from example. Please edit secrets before timer runs."
      cp "${APP_DIR}/config.example.yml" "${CONF_FILE}"
      chown "${APP_USER}:${APP_USER}" "${CONF_FILE}"
      chmod 600 "${CONF_FILE}"
    else
      log_warn "config.example.yml not found in repo; creating empty ${CONF_FILE}."
      touch "${CONF_FILE}"
      chown "${APP_USER}:${APP_USER}" "${CONF_FILE}"
      chmod 600 "${CONF_FILE}"
    fi
  else
    chmod 600 "${CONF_FILE}"
  fi
}

install_systemd_units() {
  log "Writing systemd unit files..."
  cat >"${SERVICE_FILE}" <<EOF
[Unit]
Description=mailflow-checker (SMTP->IMAP) push to Uptime Kuma
Wants=network-online.target
After=network-online.target

[Service]
Type=oneshot
User=${APP_USER}
Group=${APP_USER}
WorkingDirectory=${APP_DIR}
ExecStart=${VENV_DIR}/bin/python ${APP_DIR}/mailflow_checker.py --config ${CONF_FILE}
Nice=10
NoNewPrivileges=true
ProtectSystem=full
ProtectHome=true
PrivateTmp=true
PrivateDevices=true
LockPersonality=true
MemoryDenyWriteExecute=true

[Install]
WantedBy=multi-user.target
EOF

  cat >"${TIMER_FILE}" <<EOF
[Unit]
Description=Run ${APP_NAME} periodically

[Timer]
OnBootSec=1m
OnUnitActiveSec=${INTERVAL}
AccuracySec=30s
Unit=${APP_NAME}.service

[Install]
WantedBy=timers.target
EOF

  systemctl daemon-reload
  systemctl enable --now "${APP_NAME}.timer"
}

install_cmd() {
  require_root
  ensure_deps
  ensure_user
  clone_or_update_repo
  setup_venv
  install_config
  install_systemd_units
  log "Installation completed. Edit ${CONF_FILE} to add credentials. View logs via: journalctl -u ${APP_NAME}.service -n 100 -f"
}

update_cmd() {
  require_root
  log "Updating ${APP_NAME}..."
  systemctl stop "${APP_NAME}.service" || true
  systemctl stop "${APP_NAME}.timer" || true
  clone_or_update_repo
  setup_venv
  systemctl daemon-reload
  systemctl enable --now "${APP_NAME}.timer"
  log "Update complete."
}

uninstall_cmd() {
  require_root
  log_warn "This will remove service and timer, but keep ${CONF_FILE}. Continue? (y/N)"
  read -r ans
  if [[ "${ans}" != "y" && "${ans}" != "Y" ]]; then
    log "Aborted."
    exit 0
  fi
  systemctl stop "${APP_NAME}.timer" || true
  systemctl disable "${APP_NAME}.timer" || true
  systemctl stop "${APP_NAME}.service" || true
  systemctl disable "${APP_NAME}.service" || true
  rm -f "${SERVICE_FILE}" "${TIMER_FILE}"
  systemctl daemon-reload
  log_warn "Keeping ${APP_DIR} and ${CONF_DIR}. Remove manually if desired."
}

usage() {
  cat <<USAGE
${APP_NAME} install script

Commands:
  install    Install or re-install the service and timer
  update     Pull latest code, reinstall deps, and restart timer
  uninstall  Remove systemd units (keeps config and app dir)

Environment variables:
  E2E_REPO_URL  Git repo URL (e.g. https://github.com/OWNER/REPO.git)
  E2E_BRANCH    Branch name (default: main)
  E2E_INTERVAL  Timer interval (default: 5m)
  E2E_USER      System user (default: mailflowchecker)
USAGE
}

main() {
  local cmd="${1:-}";
  case "${cmd}" in
    install) install_cmd ;;
    update) update_cmd ;;
    uninstall) uninstall_cmd ;;
    *) usage ;;
  esac
}

main "$@"
