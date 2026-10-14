"""Owner password for a Twin Box. Off unless HEIRLOOM_BOX=1.

The hash file is not the session token. The Windows client stores the session
with DPAPI after a successful login.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from pathlib import Path


def box_mode() -> bool:
    return (os.environ.get("HEIRLOOM_BOX") or "").strip().lower() in {"1", "true", "yes", "on"}


def password_path() -> Path:
    raw = (os.environ.get("HEIRLOOM_OWNER_PASSWORD_FILE") or "").strip()
    if raw:
        return Path(raw)
    root = (os.environ.get("HEIRLOOM_DATA_ROOT") or "/var/lib/heirloom").strip() or "/var/lib/heirloom"
    return Path(root) / "owner.pass"


def set_owner_password(email: str, password: str, path: Path | None = None) -> None:
    cleaned = (email or "").strip().lower()
    if "@" not in cleaned or len(cleaned) > 200:
        raise ValueError("Email is required")
    if not password or len(password) < 8 or len(password) > 256:
        raise ValueError("Password must be 8 to 256 characters")
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, dklen=32)
    dest = path or password_path()
    dest.parent.mkdir(parents=True, exist_ok=True)
    text = f"email={cleaned}\nsalt={salt.hex()}\nhash={digest.hex()}\n"
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(dest)
    try:
        os.chmod(dest, 0o600)
    except OSError:
        pass


def _load(path: Path) -> dict[str, str]:
    found: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return found
    for line in lines:
        if "=" not in line or line.startswith("#"):
            continue
        key, _, value = line.partition("=")
        found[key.strip()] = value.strip()
    return found


def verify_owner_password(email: str, password: str, path: Path | None = None) -> bool:
    record = _load(path or password_path())
    expect_email = record.get("email") or ""
    salt_hex = record.get("salt") or ""
    hash_hex = record.get("hash") or ""
    if not expect_email or not salt_hex or not hash_hex:
        return False
    if (email or "").strip().lower() != expect_email:
        return False
    try:
        salt = bytes.fromhex(salt_hex)
        expect = bytes.fromhex(hash_hex)
    except ValueError:
        return False
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return hmac.compare_digest(digest, expect)


def main(argv: list[str] | None = None) -> int:
    import sys

    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) == 2 and args[0] == "set":
        password = sys.stdin.read().strip("\r\n")
        set_owner_password(args[1], password)
        print("Owner sign-in saved. The password was not written to the log.")
        return 0
    print("Usage: python -m box_owner set you@example.com", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
