"""Named user accounts: every decision carries the name of the person who made it.

    python -m india_rail accounts add --username sharma.r --name "R. Sharma" --role controller
    python -m india_rail accounts list | disable --username U | enable --username U

Roles: viewer (screens), controller (decisions), admin (controller + manages accounts). Devices (feeds, cab
units) do not have accounts: they hold role tokens and run-scoped capabilities instead.

* Passwords: scrypt (N=2^15, r=8, p=1) with a per-user salt; at least 12 characters, not the user name, not a
  common password. The first password set by an administrator must be changed at first login.
* Lockout: 5 wrong passwords lock the account for 15 minutes. An unknown user name costs the same scrypt as a
  known one, so the response time does not reveal which names exist.
* Sessions: a random 256-bit token returned once at login, stored only as its SHA-256. A session lasts one
  shift (SESSION_HOURS) and ends after IDLE_MINUTES without use or at logout.
* RAILGUARD_REQUIRE_ACCOUNTS=1: decisions need a personal session; the shared controller token is refused for
  them (screens may still use the shared viewer token).
* Every login, failure, lockout, password change and account change is written to the audit chain when a
  national twin is running, and always to the service log (never a password or a token).
"""

from __future__ import annotations

import argparse
import getpass
import hashlib
import hmac
import os
import secrets
import sqlite3
import sys
import threading
import time
from pathlib import Path
from typing import Any

ROLES = ("viewer", "controller", "admin")
SCRYPT = {"n": 2**15, "r": 8, "p": 1, "maxmem": 64 * 1024 * 1024, "dklen": 32}
MIN_PASSWORD = 12
MAX_FAILURES = 5
LOCK_MINUTES = 15
SESSION_HOURS = 9
IDLE_MINUTES = 60
COMMON = {"password1234", "railway12345", "indianrailways", "123456789012", "qwertyuiop12", "welcome12345",
          "administrator", "controller123", "passw0rd1234"}  # fmt: skip
USERNAME = r"^[a-z][a-z0-9._-]{2,39}$"
_DUMMY_SALT = secrets.token_bytes(16)


class AuthError(PermissionError):
    pass


def _hash(password: str, salt: bytes) -> bytes:
    return hashlib.scrypt(password.encode(), salt=salt, **SCRYPT)


def password_problem(username: str, password: str) -> str | None:
    if len(password) < MIN_PASSWORD:
        return f"at least {MIN_PASSWORD} characters"
    if len(password) > 256:
        return "at most 256 characters"
    if username.lower() in password.lower() or password.lower() in COMMON:
        return "too easy to guess (contains the user name or is a common password)"
    return None


def default_path() -> Path:
    explicit = os.environ.get("RAILGUARD_ACCOUNTS_DB")
    if explicit:
        return Path(explicit)
    state = os.environ.get("RAILGUARD_STATE_DIR")
    if state:
        return Path(state) / "accounts.sqlite"
    from india_rail.ingest import DATA_DIR

    return DATA_DIR / "accounts.sqlite"


class Accounts:
    def __init__(self, path: Path | None = None, clock=time.time):
        self.path = path or default_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.clock = clock
        self.lock = threading.Lock()
        self.con = sqlite3.connect(self.path, check_same_thread=False)
        self.con.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, display_name TEXT NOT NULL,
                role TEXT NOT NULL, salt BLOB NOT NULL, pw_hash BLOB NOT NULL, must_change INTEGER NOT NULL,
                disabled INTEGER NOT NULL DEFAULT 0, failures INTEGER NOT NULL DEFAULT 0,
                locked_until REAL NOT NULL DEFAULT 0, created_at REAL NOT NULL, last_login REAL);
            CREATE TABLE IF NOT EXISTS sessions (token_sha256 TEXT PRIMARY KEY, username TEXT NOT NULL,
                created_at REAL NOT NULL, last_seen REAL NOT NULL);
            """
        )
        self.con.commit()
        if os.name == "posix":
            os.chmod(self.path, 0o600)

    # ---- administration ----------------------------------------------------------------------------
    def add(self, username: str, display_name: str, role: str, password: str, must_change: bool = True) -> None:
        import re

        if not re.match(USERNAME, username):
            raise ValueError("user name: 3-40 of a-z 0-9 . _ - starting with a letter")
        if role not in ROLES:
            raise ValueError(f"role must be one of {ROLES}")
        if not display_name.strip() or len(display_name) > 80:
            raise ValueError("display name: 1-80 characters")
        problem = password_problem(username, password)
        if problem:
            raise ValueError(f"password: {problem}")
        salt = secrets.token_bytes(16)
        with self.lock:
            try:
                self.con.execute("INSERT INTO users (username, display_name, role, salt, pw_hash, must_change, "
                                 "created_at) VALUES (?,?,?,?,?,?,?)",
                                 (username, display_name.strip(), role, salt, _hash(password, salt), int(must_change),
                                  self.clock()))  # fmt: skip
            except sqlite3.IntegrityError as exc:
                raise ValueError("user name already exists") from exc
            self.con.commit()

    def set_disabled(self, username: str, disabled: bool) -> None:
        with self.lock:
            changed = self.con.execute("UPDATE users SET disabled = ? WHERE username = ?", (int(disabled), username))
            if disabled:
                self.con.execute("DELETE FROM sessions WHERE username = ?", (username,))
            self.con.commit()
        if not changed.rowcount:
            raise KeyError(username)

    def users(self) -> list[dict[str, Any]]:
        with self.lock:
            rows = self.con.execute("SELECT username, display_name, role, disabled, must_change, locked_until, "
                                    "last_login FROM users ORDER BY username").fetchall()  # fmt: skip
        keys = ("username", "display_name", "role", "disabled", "must_change", "locked_until", "last_login")
        return [dict(zip(keys, r, strict=True)) for r in rows]

    # ---- login and sessions ------------------------------------------------------------------------
    def login(self, username: str, password: str) -> dict[str, Any]:
        """A session token for a correct password; AuthError otherwise (same message for every failure)."""

        now = self.clock()
        with self.lock:
            row = self.con.execute("SELECT salt, pw_hash, disabled, failures, locked_until, role, display_name, "
                                   "must_change FROM users WHERE username = ?", (username,)).fetchone()  # fmt: skip
        if row is None:
            _hash(password, _DUMMY_SALT)  # same cost as a real check: no user-name enumeration by timing
            raise AuthError("wrong user name or password")
        salt, stored, disabled, failures, locked_until, role, display_name, must_change = row
        if locked_until > now:
            _hash(password, salt)
            raise AuthError("account locked after repeated failures; try again later or ask an administrator")
        ok = hmac.compare_digest(_hash(password, salt), stored)
        with self.lock:
            if not ok or disabled:
                failures = failures + 1 if not ok else failures
                lock = now + LOCK_MINUTES * 60 if failures >= MAX_FAILURES else 0
                self.con.execute("UPDATE users SET failures = ?, locked_until = ? WHERE username = ?",
                                 (0 if lock else failures, lock, username))  # fmt: skip
                self.con.commit()
                raise AuthError("wrong user name or password")
            token = secrets.token_urlsafe(32)
            self.con.execute("INSERT INTO sessions VALUES (?,?,?,?)", (_sha(token), username, now, now))
            self.con.execute("UPDATE users SET failures = 0, locked_until = 0, last_login = ? WHERE username = ?",
                             (now, username))  # fmt: skip
            self.con.commit()
        return {"token": token, "username": username, "display_name": display_name, "role": role,
                "must_change_password": bool(must_change), "expires_in_s": SESSION_HOURS * 3600}  # fmt: skip

    def session(self, token: str) -> dict[str, Any] | None:
        """The user behind a live session token (and keeps it alive), or None."""

        if not token or len(token) > 100:
            return None
        now = self.clock()
        with self.lock:
            row = self.con.execute(
                "SELECT s.username, s.created_at, s.last_seen, u.display_name, u.role, u.disabled, u.must_change "
                "FROM sessions s JOIN users u ON u.username = s.username WHERE s.token_sha256 = ?",
                (_sha(token),),
            ).fetchone()
            if row is None:
                return None
            username, created, seen, display_name, role, disabled, must_change = row
            if disabled or now - created > SESSION_HOURS * 3600 or now - seen > IDLE_MINUTES * 60:
                self.con.execute("DELETE FROM sessions WHERE token_sha256 = ?", (_sha(token),))
                self.con.commit()
                return None
            if now - seen > 30:
                self.con.execute("UPDATE sessions SET last_seen = ? WHERE token_sha256 = ?", (now, _sha(token)))
                self.con.commit()
        return {"username": username, "display_name": display_name, "role": role, "must_change": bool(must_change)}

    def logout(self, token: str) -> None:
        with self.lock:
            self.con.execute("DELETE FROM sessions WHERE token_sha256 = ?", (_sha(token),))
            self.con.commit()

    def change_password(self, username: str, old: str, new: str) -> None:
        self.login(username, old)  # proves the old password (and counts failures)
        problem = password_problem(username, new)
        if problem:
            raise ValueError(f"password: {problem}")
        if old == new:
            raise ValueError("password: the new password must differ from the old one")
        salt = secrets.token_bytes(16)
        with self.lock:
            self.con.execute("UPDATE users SET salt = ?, pw_hash = ?, must_change = 0 WHERE username = ?",
                             (salt, _hash(new, salt), username))  # fmt: skip
            self.con.execute("DELETE FROM sessions WHERE username = ?", (username,))  # every session ends
            self.con.commit()


def _sha(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


_ACCOUNTS: Accounts | None = None
_LOCK = threading.Lock()


def accounts() -> Accounts | None:
    """The process's account store, if it exists (accounts are optional until the first one is added)."""

    global _ACCOUNTS
    with _LOCK:
        if _ACCOUNTS is None or _ACCOUNTS.path != default_path():
            path = default_path()
            if not path.exists():
                return None
            _ACCOUNTS = Accounts(path)
        return _ACCOUNTS


def required() -> bool:
    return os.environ.get("RAILGUARD_REQUIRE_ACCOUNTS") == "1"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m india_rail accounts", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    add = sub.add_parser("add", help="create an account (the password is asked for, never passed as an argument)")
    add.add_argument("--username", required=True)
    add.add_argument("--name", required=True)
    add.add_argument("--role", choices=ROLES, required=True)
    sub.add_parser("list")
    for verb in ("disable", "enable"):
        sub.add_parser(verb).add_argument("--username", required=True)
    args = parser.parse_args(argv)
    store = Accounts()
    if args.command == "add":
        password = getpass.getpass("Initial password (min 12 characters; must be changed at first login): ")
        if password != getpass.getpass("Again: "):
            print("passwords differ", file=sys.stderr)
            return 1
        store.add(args.username, args.name, args.role, password)
        print(f"created {args.username} ({args.role})")
    elif args.command == "list":
        for user in store.users():
            print(user)
    else:
        store.set_disabled(args.username, args.command == "disable")
        print(f"{args.command}d {args.username}")
    return 0
