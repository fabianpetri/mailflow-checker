# mailflow-checker

An end-to-end monitoring tool that sends a test email via SMTP and verifies delivery via IMAP, reporting results to Uptime Kuma Push monitors. Designed for Debian LXC containers on Proxmox VE.

## Features
- Send test mail via SMTP (SSL/TLS, STARTTLS, or none)
- Poll IMAP mailbox for arrival with configurable timeout/interval
- Optional delete on success (mark deleted + expunge)
- Multiple accounts via YAML configuration
- Reports `status=up/down` to Uptime Kuma push URL (optional `msg`/`ping`)
- Redacts passwords in logs (no secrets in repository)

## Getting Started

### Prerequisites
- Debian-based system (Debian LXC recommended)
- Python 3

### Install (Proxmox VE community-scripts style)
You can install with a single command:

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/fabianpetri/mailflow-checker/main/scripts/install_mailflow_checker.sh)" -- install
```

Or explicitly pass your repo URL/branch:

```bash
MAILFLOW_REPO_URL="https://github.com/fabianpetri/mailflow-checker.git" MAILFLOW_BRANCH="main" \
  bash -c "$(curl -fsSL https://raw.githubusercontent.com/fabianpetri/mailflow-checker/main/scripts/install_mailflow_checker.sh)" -- install
```

This will:
- Clone to `/opt/mailflow-checker`
- Create Python venv and install dependencies
- Create `/etc/mailflow-checker/config.yml` (from `config.example.yml` if absent)
- Install a systemd service and timer (default every 5 minutes)

### Update

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/fabianpetri/mailflow-checker/main/scripts/install_mailflow_checker.sh)" -- update
```

### Uninstall (keeps config and app directory)

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/fabianpetri/mailflow-checker/main/scripts/install_mailflow_checker.sh)" -- uninstall
```

## Configuration
Copy the example and fill in credentials (do not commit secrets):

```bash
sudo cp /opt/mailflow-checker/config.example.yml /etc/mailflow-checker/config.yml
sudo chmod 600 /etc/mailflow-checker/config.yml
```

Example (`config.example.yml`):

```yaml
# defaults apply to all accounts unless overridden
defaults:
  smtp:
    port: 465
    security: ssl   # ssl | starttls | none
    timeout: 30
  imap:
    port: 993
    security: ssl   # ssl | starttls | none
    mailbox: INBOX
    timeout: 30
  poll:
    timeout_seconds: 120
    interval_seconds: 5
  delete_on_success: true

accounts:
  - name: primary
    smtp:
      host: smtp.example.com
      username: alice@example.com
      password: "CHANGE_ME"
      from: alice@example.com
      to:   alice@example.com
    imap:
      host: imap.example.com
      username: alice@example.com
      password: "CHANGE_ME"
      mailbox: INBOX
    uptime_kuma:
      push_url: "https://kuma.example.net/api/push/REPLACE_TOKEN?status=up&msg=init"
```

Notes:
- No secrets in the repository. Store passwords only in `/etc/mailflow-checker/config.yml`.
- Logs redact passwords. Avoid placing secrets in command-line arguments or environment variables.

## Running via systemd
- Timer: `mailflow-checker.timer` (defaults to every 5 minutes; override with `MAILFLOW_INTERVAL` during install)
- Service (oneshot): `mailflow-checker.service`

Useful commands:
```bash
sudo systemctl status mailflow-checker.timer
sudo journalctl -u mailflow-checker.service -n 200 -f
sudo systemctl start mailflow-checker.service
```

## Local development

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp config.example.yml config.yml
# edit config.yml with your test credentials
python mailflow_checker.py --config config.yml
```

## Security
- Passwords are never printed to logs
- Config file permissions are set to 600
- Service runs as a dedicated system user with restricted permissions

## Troubleshooting
- Verify connectivity to SMTP/IMAP hosts and ports (firewall/ACL/SSL settings)
- Ensure correct security mode (ssl/starttls/none) and ports in config
- Check mailbox name and IMAP credentials
- Review logs: `journalctl -u mailflow-checker.service -n 200 -f`
- Validate Uptime Kuma push URL token

## License
MIT (or your preferred license)

## Contributing
Issues and pull requests are welcome.
