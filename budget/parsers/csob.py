"""Parser for CSOB SK account statement CSV exports.

Expected layout:
    line 1: "Pohyby na ucte c. <IBAN> zo dna <date>"
    line 2: empty
    line 3: header ("datum zauctovania,suma,mena,...")
    rest:   one transaction per row, comma separated
"""

import io
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pandas as pd

from budget.crypto import read_maybe_encrypted
from budget.parsers import NORMALIZED_COLUMNS

HEADER_PREFIX = "datum zauctovania"
ENCODINGS = ("utf-8-sig", "cp1250")

COL_DATE = "datum zauctovania"
COL_AMOUNT = "suma"
COL_CURRENCY = "mena"
COL_TYPE = "typ transakcie"
COL_ACCOUNT = "cislo uctu protistrany"
COL_NAME = "nazov protistrany"
COL_INFO = "informacia pre prijemcu"
COL_EXTRA = "doplnujuce udaje"
REQUIRED_COLUMNS = [COL_DATE, COL_AMOUNT, COL_CURRENCY, COL_TYPE, COL_ACCOUNT, COL_NAME, COL_INFO, COL_EXTRA]

# Card payments carry the merchant in the message, e.g. "Suma: 5,00EUR 21.9.2026 Miesto: Shop".
MERCHANT_RE = re.compile(r"Miesto:\s*(.+?)\s*$")


def _read_text(path: Path, identity: object | None) -> str:
    raw = read_maybe_encrypted(path, identity)
    for encoding in ENCODINGS:
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError(f"{path}: unsupported encoding (tried {', '.join(ENCODINGS)})")


def _parse_amount(value: str) -> Decimal:
    """Parse '-11.00', '-1 234,56', '1.234,56' or '1,234.56' into a Decimal."""
    s = value.strip().replace("\xa0", "").replace(" ", "")
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".")
    return Decimal(s)


def _counterparty(name: str, message: str, account: str) -> str:
    if name:
        return name
    match = MERCHANT_RE.search(message)
    if match:
        return match.group(1)
    return account


def parse_csob(path: str | Path, identity: object | None = None) -> pd.DataFrame:
    """Parse a CSOB SK CSV export into a normalized DataFrame.

    Columns: date (datetime64), amount (float, negative = outgoing), currency,
    counterparty, message, raw_category (CSOB transaction type).
    A file ending in .age is decrypted with `identity` (see budget.crypto.unlock).
    Raises ValueError on malformed input; messages never include row contents.
    """
    path = Path(path)
    lines = _read_text(path, identity).splitlines(keepends=True)
    header_idx = next(
        (i for i, line in enumerate(lines) if line.strip().lower().startswith(HEADER_PREFIX)),
        None,
    )
    if header_idx is None:
        raise ValueError(f"{path}: header row starting with '{HEADER_PREFIX}' not found")

    raw = pd.read_csv(
        io.StringIO("".join(lines[header_idx:])),
        dtype=str,
        keep_default_na=False,
    )
    raw.columns = [c.strip().lower() for c in raw.columns]
    missing = [c for c in REQUIRED_COLUMNS if c not in raw.columns]
    if missing:
        raise ValueError(f"{path}: missing columns: {', '.join(missing)}")

    raw = raw[REQUIRED_COLUMNS].apply(lambda col: col.str.strip())
    raw = raw[(raw != "").any(axis=1)].reset_index(drop=True)

    dates = pd.to_datetime(raw[COL_DATE], format="%d.%m.%Y", errors="coerce")
    bad_dates = dates.isna()
    if bad_dates.any():
        rows = ", ".join(str(i + 1) for i in raw.index[bad_dates][:10])
        raise ValueError(f"{path}: invalid date in data row(s) {rows}")

    amounts = []
    for i, value in enumerate(raw[COL_AMOUNT]):
        try:
            amounts.append(float(_parse_amount(value)))
        except InvalidOperation:
            raise ValueError(f"{path}: invalid amount in data row {i + 1}") from None

    messages = [
        f"{info} | {extra}" if info and extra else info or extra
        for info, extra in zip(raw[COL_INFO], raw[COL_EXTRA])
    ]
    counterparties = [
        _counterparty(name, info, account)
        for name, info, account in zip(raw[COL_NAME], raw[COL_INFO], raw[COL_ACCOUNT])
    ]

    df = pd.DataFrame(
        {
            "date": dates,
            "amount": amounts,
            "currency": raw[COL_CURRENCY],
            "counterparty": counterparties,
            "message": messages,
            "raw_category": raw[COL_TYPE],
        }
    )
    return df[NORMALIZED_COLUMNS]
