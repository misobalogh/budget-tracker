"""Anonymization of sensitive transactions before any output.

private.yaml (gitignored, optional; may be encrypted as private.yaml.age, see budget.crypto):
    patterns:
      - 'some-merchant'   # case-insensitive regex, searched in counterparty and message
Matching transactions keep their date, amount and raw_category, but counterparty
and message are replaced with PLACEHOLDER. Rules can target them via
`counterparty: '^<private>$'`.
"""

import re
from pathlib import Path

import pandas as pd
import yaml

from budget.crypto import RECIPIENT_FILE, decrypt_bytes, encrypt_bytes, encrypted_path, load_recipient
from budget.fileio import write_bytes_atomic, write_text_atomic

PLACEHOLDER = "<private>"
HEADER = (
    "# Transactions matching any pattern (case-insensitive regex, searched in counterparty\n"
    "# and message) are shown as <private> in all outputs.\n"
)


def read_pattern_strings(path: str | Path, identity: object | None = None) -> list[str]:
    """Pattern strings from private.yaml.age (needs the unlocked key) or private.yaml; none if neither exists."""
    path = Path(path)
    enc = encrypted_path(path)
    if enc.exists():
        if identity is None:
            raise ValueError(f"{enc.name} is encrypted: a password is required")
        text = decrypt_bytes(enc.read_bytes(), identity, enc.name).decode("utf-8")
    elif path.exists():
        text = path.read_text(encoding="utf-8")
    else:
        return []
    data = yaml.safe_load(text) or {}
    return [str(p) for p in data.get("patterns") or []]


def write_pattern_strings(path: str | Path, patterns: list[str], data_dir: str | Path | None = None) -> Path:
    """Save patterns: to private.yaml.age when it exists, or when a new file is created and a key is available.

    Returns the file written. Encrypting needs only the public key, never the password.
    """
    path = Path(path)
    enc = encrypted_path(path)
    for i, pattern in enumerate(patterns, start=1):
        _compile(pattern, f"pattern {i}")
    text = HEADER + yaml.safe_dump({"patterns": patterns}, default_flow_style=False)
    has_key = data_dir is not None and (Path(data_dir) / RECIPIENT_FILE).exists()
    if enc.exists() or (has_key and not path.exists()):  # an existing plain file stays plain until encrypted
        write_bytes_atomic(enc, encrypt_bytes(text.encode("utf-8"), load_recipient(data_dir)))
        return enc
    write_text_atomic(path, text)
    return path


def _compile(pattern: str, what: str) -> re.Pattern:
    try:
        return re.compile(pattern, re.IGNORECASE)
    except re.error as exc:
        raise ValueError(f"invalid regex in {what}: {exc}") from None


def load_private_patterns(path: str | Path, identity: object | None = None) -> list[re.Pattern]:
    """Compile the patterns of private.yaml(.age); a missing file means no patterns."""
    try:
        return [_compile(p, f"pattern {i}") for i, p in enumerate(read_pattern_strings(path, identity), start=1)]
    except ValueError as exc:
        raise ValueError(f"{Path(path).name}: {exc}") from None


def anonymize(df: pd.DataFrame, patterns: list[re.Pattern]) -> pd.DataFrame:
    """Return a copy of df with counterparty and message masked on matching rows."""
    out = df.copy()
    if not patterns:
        return out
    mask = [
        any(p.search(cp) or p.search(msg) for p in patterns)
        for cp, msg in zip(out["counterparty"], out["message"])
    ]
    out.loc[mask, ["counterparty", "message"]] = PLACEHOLDER
    return out
