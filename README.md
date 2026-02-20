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

## Configuring Uptime Kuma
Uptime Kuma should be configured with a Push monitor for each account you want to track. The application will call the Push URL after each run with `status`, `msg`, and optional `ping`.

Step-by-step:
1) In Uptime Kuma, click "Add New Monitor".
2) Type: "Push".
3) Name: e.g., "Mailflow – primary".
4) Heartbeat Interval: set slightly higher than how often this checker runs. If you use the default systemd timer (every 5 minutes), set 6–7 minutes to allow for jitter.
5) Copy the generated Push URL.
6) Paste that URL into your `config.yml` under the corresponding account as `uptime_kuma.push_url`:
   - Example: `https://your-kuma.example/api/push/<TOKEN>` (you do not need to append query parameters; the script adds `status`, `msg`, and `ping` automatically.)

What the script sends to Uptime Kuma:
- status: "up" on success, "down" on failure.
- msg: short human-readable result (e.g., "OK", "SMTP failed: ...", "IMAP timeout: message not found"). Truncated to 200 chars.
- ping: integer milliseconds representing the SMTP send duration only (IMAP polling time is not included).

Recommendations and tips:
- One token per monitored mailflow: If you configure multiple accounts, create a separate Push monitor (token) for each and put the corresponding `push_url` on each account.
- Grouping: Use Uptime Kuma tags or groups (folders) to keep related accounts together.
- Interval alignment: If you change the systemd timer interval (via `MAILFLOW_INTERVAL`, default 5m), also adjust each monitor's Heartbeat Interval to be a bit larger than the new cadence.
- No Push URL? If `uptime_kuma.push_url` is omitted for an account, the checker still runs but won't report to Kuma.
- Status page integration: Push monitors work the same as other monitors; you can include them on status pages.

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
      push_url: "https://kuma.example.net/api/push/REPLACE_TOKEN"
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

## Configuring Uptime Kuma

- In Uptime Kuma, create a new monitor of type "Push" for each account you want to track.
- Copy the Push URL (it looks like https://<kuma-host>/api/push/<token> ).
- Put this value into your account config as uptime_kuma.push_url. Use the base token URL (no query parameters). Example:

```yaml
accounts:
  - name: primary
    # ... smtp/imap ...
    uptime_kuma:
      push_url: "https://kuma.example.net/api/push/<TOKEN>"
```

- Heartbeat Interval: Set slightly above your systemd timer (e.g., timer 5m -> interval 6–7m) to avoid false alerts.
- Heartbeat Retries: 0–1 for fast alerts, 2 if you want more noise damping.
- The script sends: status=up|down, msg (short reason or OK), and ping (milliseconds for SMTP phase).
- Avoid using additional keepalive scripts against the same monitor—those can mask real failures.

### Test your Push token quickly

You can test your configured Push URL(s) without sending mail:

```bash
# Test all accounts' tokens in the config
python mailflow_checker.py --config /etc/mailflow-checker/config.yml --test-kuma

# Test only a specific account's token
python mailflow_checker.py --config /etc/mailflow-checker/config.yml --account primary --test-kuma
```

A successful test logs something like:

```
INFO Kuma token OK: https://kuma.../api/push/<TOKEN> (status=200, body={"ok":true,...})
```

If it fails, you'll see an error with status/body details to help diagnose (token invalid, Kuma offline, network/firewall, etc.).

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
