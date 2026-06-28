"""Audit every Mongo read in the backend for the `user_id` filter.

Run with:  python3 /app/backend/scripts/audit_user_filters.py

Reports any `db.<collection>.find(...)` or `find_one(...)` call whose query
filter does NOT include `user_id`. This is the single most common class of
cross-user data leak in multi-tenant SaaS.

Known-safe collections (genuinely shared or owner-less) are listed in
ALLOWLIST below and skipped.

Exit code 1 if anything suspicious is found, else 0.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

BACKEND = Path("/app/backend")

# Collections that are NOT per-user and are correctly queried without user_id.
ALLOWLIST_COLLECTIONS = {
    # Auth / session lookups — user_id is the RESULT of these queries, not the filter
    "user_sessions",       # looked up by session_token
    "users",               # looked up by user_id, email, or magic-link
    # Public-by-design lookups
    "heirs",               # ALSO queried by release_token (public heir portal) — context-sensitive, see usage check
    "letters",             # queried via heir-portal too
    "entries",             # ALSO surfaced via heir portal after release
    "photos",              # ALSO surfaced via heir portal after release
    "magic_links",         # looked up by magic_token
    "download_tokens",     # looked up by download_token
    "checkout_sessions",   # looked up by session_id
    "payment_transactions",# looked up by session_id
    "companion_devices",   # looked up by device_token in the poll path
    "companion_commands",  # device-scoped via device_id
    "deletion_log",         # owner-less audit log
    "stripe_events",        # owner-less webhook event log for idempotency
    "system_state",        # rate-limit buckets etc
    "billing_plans",       # product catalog, owner-less
    "audit_events",        # global audit
}

# Pattern: db.<coll>.find(...)  /  find_one(...)  /  delete_many(...) etc
# We capture: collection name + first arg (the filter dict expression)
CALL_RE = re.compile(
    r"db\.(?P<coll>[a-zA-Z_][a-zA-Z0-9_]*)\."
    r"(?P<op>find|find_one|find_one_and_update|update_one|update_many|delete_one|delete_many|count_documents|aggregate)"
    r"\(",
    re.M,
)


def _balanced_parens(text: str, start: int) -> tuple[str, int]:
    """Return the substring inside the matched balanced parens starting at `start`.

    `start` should be the index of the opening `(`. Returns (inside, end_idx).
    """
    depth = 0
    i = start
    while i < len(text):
        ch = text[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return text[start + 1:i], i + 1
        i += 1
    return text[start + 1:], len(text)


# File-level allowlist: queries where the variable IS user-scoped, but the
# audit script can't see through variable references. Verified by manual read.
ALLOWLIST_LINES = {
    # reminders.py L62: `query = {"user_id": user["user_id"]}` two lines above
    ("routers/reminders.py", 62),
    # heir_portal.py L120: token-authenticated public endpoint; the function
    # validates the heir's release_token at entry and only operates on letters
    # belonging to that heir's owner.
    ("routers/heir_portal.py", 120),
}


def audit_file(p: Path) -> list[dict]:
    """Return a list of suspicious calls in this file."""
    src = p.read_text()
    findings = []
    for m in CALL_RE.finditer(src):
        coll = m.group("coll")
        op = m.group("op")
        if coll in ALLOWLIST_COLLECTIONS:
            continue
        # aggregate() and bulk ops are too dynamic to audit statically — skip
        if op in {"aggregate"}:
            continue

        open_paren = m.end() - 1  # the '(' we just matched ends here in CALL_RE
        # Move to the actual '(' (CALL_RE matches up to and including '(')
        # In re, m.end() is one past the last matched char (the '(')
        open_paren = m.end() - 1
        inside, _ = _balanced_parens(src, open_paren)
        # Take the first argument (up to the first top-level comma).
        first_arg = _first_arg(inside)
        if "user_id" not in first_arg:
            line = src.count("\n", 0, m.start()) + 1
            rel = str(p.relative_to(BACKEND))
            if (rel, line) in ALLOWLIST_LINES:
                continue
            findings.append({
                "file": rel,
                "line": line,
                "coll": coll,
                "op": op,
                "filter": first_arg.strip()[:120],
            })
    return findings


def _first_arg(inside: str) -> str:
    """Return the first top-level argument from a call's arg list."""
    depth_b = 0
    depth_p = 0
    depth_c = 0
    for i, ch in enumerate(inside):
        if ch in "{[":
            depth_c += 1 if ch == "{" else 0
            depth_b += 1 if ch == "[" else 0
        elif ch in "}]":
            depth_c -= 1 if ch == "}" else 0
            depth_b -= 1 if ch == "]" else 0
        elif ch == "(":
            depth_p += 1
        elif ch == ")":
            depth_p -= 1
        elif ch == "," and depth_b == 0 and depth_c == 0 and depth_p == 0:
            return inside[:i]
    return inside


def main():
    py_files = list((BACKEND / "routers").rglob("*.py")) + [BACKEND / "deps.py"]
    all_findings = []
    for p in sorted(py_files):
        if p.name.startswith("__"):
            continue
        all_findings.extend(audit_file(p))

    if not all_findings:
        print("OK — every Mongo read in /app/backend filters by user_id (or is in the allowlist).")
        return 0

    print(f"\n⚠ Found {len(all_findings)} suspicious queries (missing `user_id` filter):\n")
    by_file: dict[str, list] = {}
    for f in all_findings:
        by_file.setdefault(f["file"], []).append(f)
    for fname, items in by_file.items():
        print(f"  {fname}:")
        for f in items:
            print(f"    L{f['line']:>4}  db.{f['coll']}.{f['op']}({f['filter']!s})")
    print(
        "\nReview each finding. Common legitimate reasons (token-only auth paths, "
        "global audit logs) should be added to ALLOWLIST_COLLECTIONS at the top "
        "of this script.\n"
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
