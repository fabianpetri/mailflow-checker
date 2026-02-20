#!/usr/bin/env python3
import argparse
import email
import email.utils
import logging
import smtplib
import socket
import ssl
import sys
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import imaplib
import yaml
import requests

REDACTED = "***REDACTED***"


def setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(message)s",
    )


def redact_config(obj: Any) -> Any:
    if isinstance(obj, dict):
        redacted = {}
        for k, v in obj.items():
            if k.lower() in {"password", "pass", "secret", "token", "push_key"}:
                redacted[k] = REDACTED
            else:
                redacted[k] = redact_config(v)
        return redacted
    if isinstance(obj, list):
        return [redact_config(x) for x in obj]
    return obj


@dataclass
class SMTPSettings:
    host: str
    port: int = 465
    security: str = "ssl"  # ssl, starttls, none
    username: Optional[str] = None
    password: Optional[str] = None
    from_addr: Optional[str] = None
    to_addr: Optional[str] = None
    timeout: int = 30


@dataclass
class IMAPSettings:
    host: str
    port: int = 993
    security: str = "ssl"  # ssl, starttls, none
    username: Optional[str] = None
    password: Optional[str] = None
    mailbox: str = "INBOX"
    timeout: int = 30


@dataclass
class PollSettings:
    timeout_seconds: int = 120
    interval_seconds: int = 5


@dataclass
class KumaSettings:
    push_url: Optional[str] = None


@dataclass
class AccountConfig:
    name: str
    smtp: SMTPSettings
    imap: IMAPSettings
    poll: PollSettings = field(default_factory=PollSettings)
    delete_on_success: bool = True
    kuma: KumaSettings = field(default_factory=KumaSettings)


def deep_merge(a: Dict[str, Any], b: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(a)
    for k, v in b.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def parse_config(path: str, selected_accounts: Optional[List[str]] = None) -> List[AccountConfig]:
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    defaults = data.get("defaults", {})
    accounts = data.get("accounts", [])
    if not accounts:
        raise ValueError("No accounts configured in YAML under 'accounts'.")

    result: List[AccountConfig] = []
    for raw in accounts:
        if selected_accounts and raw.get("name") not in selected_accounts:
            continue
        merged = deep_merge(defaults, raw)
        # Map keys to dataclasses
        smtp_dict = merged.get("smtp") or {}
        imap_dict = merged.get("imap") or {}
        poll_dict = merged.get("poll") or {}
        kuma_dict = merged.get("uptime_kuma") or merged.get("kuma") or {}

        # Normalize keys
        smtp = SMTPSettings(
            host=str(smtp_dict.get("host")),
            port=int(smtp_dict.get("port", 465)),
            security=str(smtp_dict.get("security", "ssl")).lower(),
            username=smtp_dict.get("username"),
            password=smtp_dict.get("password"),
            from_addr=smtp_dict.get("from") or smtp_dict.get("from_addr"),
            to_addr=smtp_dict.get("to") or smtp_dict.get("to_addr"),
            timeout=int(smtp_dict.get("timeout", 30)),
        )
        imap = IMAPSettings(
            host=str(imap_dict.get("host")),
            port=int(imap_dict.get("port", 993)),
            security=str(imap_dict.get("security", "ssl")).lower(),
            username=imap_dict.get("username"),
            password=imap_dict.get("password"),
            mailbox=str(imap_dict.get("mailbox", "INBOX")),
            timeout=int(imap_dict.get("timeout", 30)),
        )
        poll = PollSettings(
            timeout_seconds=int(poll_dict.get("timeout_seconds", poll_dict.get("timeout", 120))),
            interval_seconds=int(poll_dict.get("interval_seconds", poll_dict.get("interval", 5))),
        )
        kuma = KumaSettings(
            push_url=kuma_dict.get("push_url") or kuma_dict.get("url")
        )
        delete_on_success = bool(merged.get("delete_on_success", merged.get("cleanup", True)))

        name = str(merged.get("name") or raw.get("name"))
        if not name:
            raise ValueError("Each account must have a 'name'.")

        # Basic validation
        for fld, label in [
            (smtp.host, "smtp.host"),
            (imap.host, "imap.host"),
        ]:
            if not fld:
                raise ValueError(f"Missing required config value: {label} for account {name}")

        result.append(AccountConfig(name=name, smtp=smtp, imap=imap, poll=poll, delete_on_success=delete_on_success, kuma=kuma))

    if selected_accounts and not result:
        raise ValueError("No matching accounts after filtering by --account")

    logging.debug("Loaded config: %s", redact_config(data))
    return result


def build_message(from_addr: str, to_addr: str, subject_prefix: str = "Stalwart E2E Monitor") -> Tuple[str, bytes, str]:
    token = uuid.uuid4().hex
    msg_id = f"<{token}@e2e-monitor>"
    subject = f"{subject_prefix} token={token}"
    now = email.utils.formatdate(localtime=True)
    headers = [
        f"From: {from_addr}",
        f"To: {to_addr}",
        f"Subject: {subject}",
        f"Date: {now}",
        f"Message-ID: {msg_id}",
        "MIME-Version: 1.0",
        "Content-Type: text/plain; charset=utf-8",
        "Content-Transfer-Encoding: 8bit",
    ]
    body = (
        "This is an automated E2E monitoring email.\n"
        f"Token: {token}\n"
        f"Time: {now}\n"
    )
    raw = ("\r\n".join(headers) + "\r\n\r\n" + body).encode("utf-8")
    return token, raw, msg_id


def smtp_send(cfg: SMTPSettings, raw_message: bytes) -> float:
    start = time.time()
    context = ssl.create_default_context()
    logging.debug("Preparing SMTP connection to %s:%s security=%s", cfg.host, cfg.port, cfg.security)
    if cfg.security == "ssl":
        with smtplib.SMTP_SSL(cfg.host, cfg.port, timeout=cfg.timeout, context=context) as s:
            s.ehlo()
            if cfg.username and cfg.password:
                s.login(cfg.username, cfg.password)
            s.sendmail(cfg.from_addr, [cfg.to_addr], raw_message)
    else:
        with smtplib.SMTP(cfg.host, cfg.port, timeout=cfg.timeout) as s:
            s.ehlo()
            if cfg.security == "starttls":
                s.starttls(context=context)
                s.ehlo()
            if cfg.username and cfg.password:
                s.login(cfg.username, cfg.password)
            s.sendmail(cfg.from_addr, [cfg.to_addr], raw_message)
    return (time.time() - start) * 1000.0


def imap_connect(cfg: IMAPSettings):
    logging.debug("Connecting IMAP to %s:%s security=%s", cfg.host, cfg.port, cfg.security)
    if cfg.security == "ssl":
        imap = imaplib.IMAP4_SSL(cfg.host, cfg.port)
    else:
        imap = imaplib.IMAP4(cfg.host, cfg.port)
        if cfg.security == "starttls":
            imap.starttls(ssl_context=ssl.create_default_context())
    if cfg.username and cfg.password:
        imap.login(cfg.username, cfg.password)
    return imap


def imap_search_for_token(imap: imaplib.IMAP4, mailbox: str, token: str, msg_id: str) -> Optional[bytes]:
    typ, _ = imap.select(mailbox, readonly=False)
    if typ != 'OK':
        raise RuntimeError(f"Failed to select mailbox {mailbox}: {typ}")

    # Prefer Message-ID search (exact)
    criteria_list = [
        f'(HEADER Message-ID "{msg_id}")',
        f'(SUBJECT "{token}")',
        f'(TEXT "{token}")',
    ]
    for crit in criteria_list:
        typ, data = imap.search(None, crit)
        if typ == 'OK' and data and len(data) > 0:
            ids = data[0].split()
            if ids:
                return ids[-1]  # latest match
    return None


def imap_delete(imap: imaplib.IMAP4, mailbox: str, msgid: bytes) -> None:
    imap.store(msgid, '+FLAGS', r'(\Deleted)')
    imap.expunge()


def push_kuma(url: str, status: str, msg: Optional[str] = None, ping_ms: Optional[float] = None) -> None:
    params = {"status": status}
    if msg:
        # Truncate overly long messages
        params["msg"] = msg[:200]
    if ping_ms is not None:
        params["ping"] = f"{int(ping_ms)}"
    try:
        r = requests.get(url, params=params, timeout=10)
        r.raise_for_status()
        logging.info("Reported to Uptime Kuma: %s status=%s", url, status)
    except Exception as e:
        logging.error("Failed to push status to Uptime Kuma: %s", e)


def run_for_account(acct: AccountConfig) -> Tuple[bool, str, Optional[float]]:
    # Basic field validation to avoid SMTP/IMAP errors with None values
    for field_name, val in [
        ("smtp.from", acct.smtp.from_addr),
        ("smtp.to", acct.smtp.to_addr),
        ("smtp.host", acct.smtp.host),
        ("imap.host", acct.imap.host),
    ]:
        if not val:
            raise ValueError(f"Account {acct.name}: missing required field {field_name}")

    token, raw, msg_id = build_message(acct.smtp.from_addr, acct.smtp.to_addr)

    smtp_ms = None
    try:
        smtp_ms = smtp_send(acct.smtp, raw)
        logging.info("%s: SMTP sent ok (%.0f ms) token=%s", acct.name, smtp_ms, token)
    except (smtplib.SMTPException, socket.error) as e:
        logging.error("%s: SMTP send failed: %s", acct.name, e)
        return False, f"SMTP failed: {type(e).__name__}: {e}", smtp_ms

    deadline = time.time() + acct.poll.timeout_seconds
    try:
        imap = imap_connect(acct.imap)
    except Exception as e:
        logging.error("%s: IMAP connect/login failed: %s", acct.name, e)
        return False, f"IMAP connect failed: {type(e).__name__}: {e}", smtp_ms

    try:
        found_id: Optional[bytes] = None
        while time.time() < deadline:
            try:
                found_id = imap_search_for_token(imap, acct.imap.mailbox, token, msg_id)
                if found_id:
                    break
            except Exception as e:
                logging.debug("%s: search transient error: %s", acct.name, e)
            time.sleep(acct.poll.interval_seconds)
        if not found_id:
            logging.error("%s: Message not found within timeout (token=%s)", acct.name, token)
            return False, "IMAP timeout: message not found", smtp_ms

        if acct.delete_on_success:
            try:
                imap_delete(imap, acct.imap.mailbox, found_id)
            except Exception as e:
                logging.warning("%s: Could not delete message id %s: %s", acct.name, found_id, e)

        total_ms = None
        if smtp_ms is not None:
            total_ms = smtp_ms  # we only measured SMTP separately; IMAP poll time is implicit in timeout
        logging.info("%s: End-to-end success (token=%s)", acct.name, token)
        return True, "OK", total_ms
    finally:
        try:
            imap.logout()
        except Exception:
            pass


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Stalwart Mail Server E2E Monitor")
    p.add_argument("--config", "-c", default="config.yml", help="Path to YAML config (default: config.yml)")
    p.add_argument("--account", "-a", action="append", help="Run only for the given account name (repeatable)")
    p.add_argument("--verbose", "-v", action="store_true", help="Enable debug logging")
    args = p.parse_args(argv)

    setup_logging(args.verbose)

    try:
        accounts = parse_config(args.config, args.account)
    except Exception as e:
        logging.error("Config error: %s", e)
        return 2

    overall_ok = True
    for acct in accounts:
        logging.info("Running monitor for account: %s", acct.name)
        ok, msg, ping_ms = run_for_account(acct)
        overall_ok = overall_ok and ok
        if acct.kuma.push_url:
            try:
                push_kuma(acct.kuma.push_url, status="up" if ok else "down", msg=msg, ping_ms=ping_ms)
            except Exception:
                pass
        if not ok:
            # do not break; report each account independently
            logging.warning("Account %s failed: %s", acct.name, msg)

    return 0 if overall_ok else 1


if __name__ == "__main__":
    sys.exit(main())
