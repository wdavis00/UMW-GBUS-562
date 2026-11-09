#!/usr/bin/env python3
"""load_inbox.py - put the sample HR emails into a Gmail sandbox inbox as unread messages.

Signs in to Gmail with IMAP and uses APPEND to place each .eml file from
week-04/hartwell-hr/sample-emails/ directly into INBOX. Nothing is sent: no SMTP is used,
and the messages never leave your mailbox.

Each message gets:
  - today's date (both the Date: header and the date Gmail shows/sorts by),
  - a fresh Message-ID, so Gmail doesn't merge repeated loads into one message,
  - no \\Seen flag, so it arrives unread.

Login: read at run time from Agent-Email.txt in the folder above the repository.
Either of these formats works:

    you@gmail.com                 EMAIL=you@gmail.com
    abcd efgh ijkl mnop           PASSWORD=abcd efgh ijkl mnop

(The password should be a Gmail app password; spaces in it are removed.)
The password is never printed, logged, or written to any file.

Usage (from the repo root):
  .venv/bin/python week-04/load_inbox.py           # place the emails in the inbox
  .venv/bin/python week-04/load_inbox.py --check   # check the login file offline, no sign-in
"""

from __future__ import annotations

import imaplib
import re
import sys
import time
from email import policy
from email.parser import BytesParser
from email.utils import formatdate, make_msgid
from pathlib import Path

HERE = Path(__file__).resolve().parent                 # .../UMW-GBUS-562/week-04
REPO_ROOT = HERE.parent
LOGIN_FILE = REPO_ROOT.parent / "Agent-Email.txt"
EMAILS_DIR = HERE / "hartwell-hr" / "sample-emails"
IMAP_HOST = "imap.gmail.com"
MAILBOX = "INBOX"
# Only a value matching this is ever printed, so a misread password line can't be shown.
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def load_login() -> tuple[str, str]:
    """Return (address, password) from LOGIN_FILE. Never prints the password."""
    if not LOGIN_FILE.is_file():
        sys.exit(f"Login file not found: {LOGIN_FILE}")
    lines = [ln.strip() for ln in LOGIN_FILE.read_text(encoding="utf-8").splitlines() if ln.strip()]
    address = password = ""
    plain: list[str] = []
    for ln in lines:
        if ln.startswith("#"):
            continue
        key, sep, val = ln.partition("=")
        key = key.strip().upper()
        val = val.strip().strip('"').strip("'")
        # Any KEY=value line: a key containing PASS (or KEY/SECRET) is the password;
        # a key containing EMAIL/USER/ADDRESS/LOGIN is the address.
        if sep and key.replace("_", "").replace("-", "").isalnum():
            if any(w in key for w in ("PASS", "PW", "SECRET", "KEY", "TOKEN")):
                password = password or val
            elif any(w in key for w in ("EMAIL", "USER", "ADDRESS", "LOGIN", "ACCOUNT")):
                address = address or val
            continue
        plain.append(ln)
    if not address and plain:
        address = plain.pop(0)
    if not password and plain:
        password = plain.pop(0)
    password = password.replace(" ", "")
    if not EMAIL_RE.fullmatch(address) or not password:
        # Say which part is missing, without echoing anything from the file.
        missing = [n for n, ok in (("a valid email address", EMAIL_RE.fullmatch(address)),
                                   ("a password", password)) if not ok]
        sys.exit(f"Could not find {' or '.join(missing)} in {LOGIN_FILE.name}. Use one per "
                 "line, or EMAIL_ADDRESS=... and PASSWORD=... lines.")
    return address, password


def prepare(path: Path) -> bytes:
    """Return the email as bytes with today's Date: and a new Message-ID."""
    with path.open("rb") as f:
        msg = BytesParser(policy=policy.default).parse(f)
    del msg["Date"]
    del msg["Message-ID"]
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain="hartwellfoods.example")
    return msg.as_bytes(policy=policy.SMTP)  # CRLF line endings, as IMAP expects


def main() -> None:
    files = sorted(p for p in EMAILS_DIR.glob("*.eml") if p.is_file())
    if not files:
        sys.exit(f"No .eml files found in {EMAILS_DIR}")

    address, password = load_login()
    if "--check" in sys.argv[1:]:
        # Offline check of the login file: shows the password's shape, never its value.
        looks_ok = len(password) == 16 and password.isalpha()
        print(f"Address:  {address}")
        print(f"Password: {len(password)} characters, "
              f"{'letters only' if password.isalpha() else 'includes non-letters'}")
        print("Looks like a Gmail app password (16 letters)." if looks_ok else
              "Does NOT look like a Gmail app password, which is 16 letters "
              "(spaces are removed automatically).")
        return
    print(f"Signing in to {IMAP_HOST} as {address} ...")
    try:
        imap = imaplib.IMAP4_SSL(IMAP_HOST)
    except OSError as e:
        sys.exit(f"Could not connect to {IMAP_HOST}: {e}")

    try:
        try:
            imap.login(address, password)
        except imaplib.IMAP4.error as e:
            # Gmail's reply (e.g. "[AUTHENTICATIONFAILED] Invalid credentials") never
            # contains the password, so it is safe to show.
            reason = e.args[0].decode(errors="replace") if e.args and isinstance(e.args[0], bytes) else str(e)
            sys.exit(f"Sign-in failed: {reason}\nCheck the address and app password in "
                     f"{LOGIN_FILE.name}, and that IMAP is enabled for the account.")
        finally:
            del password

        loaded = 0
        for path in files:
            data = prepare(path)
            status, resp = imap.append(MAILBOX, "", imaplib.Time2Internaldate(time.time()), data)
            if status == "OK":
                loaded += 1
                print(f"  placed (unread): {path.name}")
            else:
                print(f"  FAILED: {path.name}: {resp}")
        print(f"\nDone: {loaded} of {len(files)} emails placed in {MAILBOX}. Nothing was sent.")
    finally:
        try:
            imap.logout()
        except Exception:
            pass


if __name__ == "__main__":
    main()
