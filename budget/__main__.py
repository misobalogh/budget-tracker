"""Command line interface: python -m budget <command>."""

import argparse
import getpass
import re
import sys
import threading
import webbrowser
from pathlib import Path

from budget.categorizer import categorize, load_rules
from budget.crypto import (
    ENCRYPTED_SUFFIX,
    WrongPassphrase,
    encrypt_bytes,
    encrypted_path,
    init_keys,
    load_recipient,
    needs_unlock,
    unlock,
)
from budget.fileio import write_bytes_atomic
from budget.parsers.csob import parse_csob
from budget.privacy import anonymize, load_private_patterns, read_pattern_strings, write_pattern_strings
from budget.report import counterparty_stats, format_summary, load_transactions, monthly_summary

MAX_PASSWORD_TRIES = 3


def read_passphrase(prompt: str) -> str:
    """Ask for a password without echoing it (a seam for tests)."""
    return getpass.getpass(prompt)


def unlock_with_prompt(data_dir: str | Path):
    """Ask for the password (a few tries) and return the unlocked key."""
    for _ in range(MAX_PASSWORD_TRIES):
        try:
            return unlock(data_dir, read_passphrase("Password: "))
        except WrongPassphrase:
            print("Wrong password.", file=sys.stderr)
    raise ValueError("too many wrong passwords")


def unlock_if_needed(data_dir: str | Path, private_path: str | Path):
    """The unlocked key when encrypted exports or private.yaml.age exist, otherwise None."""
    return unlock_with_prompt(data_dir) if needs_unlock(data_dir, private_path) else None


def cmd_check(args: argparse.Namespace) -> int:
    """Parse a file and print aggregates only (no amounts, names or messages)."""
    try:
        path = Path(args.csv)
        identity = unlock_with_prompt(path.parent) if path.suffix == ENCRYPTED_SUFFIX else None
        df = parse_csob(path, identity)
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"rows: {len(df)}")
    if df.empty:
        return 0
    print(f"date range: {df['date'].min():%Y-%m-%d} .. {df['date'].max():%Y-%m-%d}")
    print(f"incoming / outgoing / zero: {(df['amount'] > 0).sum()} / {(df['amount'] < 0).sum()} / {(df['amount'] == 0).sum()}")
    print(f"currencies: {df['currency'].value_counts().to_dict()}")
    print(f"empty counterparty: {(df['counterparty'] == '').sum()}")
    print(f"empty message: {(df['message'] == '').sum()}")
    print("transaction types (raw_category):")
    for name, count in df["raw_category"].value_counts().items():
        print(f"  {count:5d}  {name or '<empty>'}")
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    """Print the monthly summary and the list of uncategorized transactions."""
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", args.month):
        print(f"ERROR: --month must be YYYY-MM, got '{args.month}'", file=sys.stderr)
        return 2
    try:
        ruleset = load_rules(args.rules)
        identity = unlock_if_needed(args.data, args.private)
        df = anonymize(load_transactions(args.data, identity), load_private_patterns(args.private, identity))
        df = categorize(df, ruleset)
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(format_summary(monthly_summary(df, args.month)))
    return 0


def cmd_counterparties(args: argparse.Namespace) -> int:
    """Print unique counterparties with counts (no amounts or messages), safe to share."""
    if args.month and not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", args.month):
        print(f"ERROR: --month must be YYYY-MM, got '{args.month}'", file=sys.stderr)
        return 2
    try:
        identity = unlock_if_needed(args.data, args.private)
        df = anonymize(load_transactions(args.data, identity), load_private_patterns(args.private, identity))
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    stats = counterparty_stats(df, args.month, args.exclude_type)
    for row in stats.itertuples():
        print(f"{row.count:4d}  {row.counterparty} | {row.raw_category}")
    return 0


WEB_DIST = Path(__file__).resolve().parent.parent / "web" / "dist"


def cmd_ui(args: argparse.Namespace) -> int:
    """Serve the web UI and its API on 127.0.0.1 only."""
    import uvicorn

    from budget.api import create_app

    static_dir = None if args.dev else WEB_DIST
    if static_dir is not None and not static_dir.is_dir():
        print("ERROR: web UI is not built. Run: cd web && npm install && npm run build", file=sys.stderr)
        print("       (or use --dev together with `npm run dev`)", file=sys.stderr)
        return 1
    try:
        identity = unlock_if_needed(args.data, args.private)
        app = create_app(args.data, args.rules, args.private, static_dir, budgets_path=args.budgets, identity=identity)
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    url = f"http://127.0.0.1:{args.port}"
    print(f"API only on {url}/api (start the frontend with: cd web && npm run dev)" if args.dev else f"Budget UI on {url}")
    if not args.dev and not args.no_browser:
        threading.Timer(1.0, webbrowser.open, args=(url,)).start()
    uvicorn.run(app, host="127.0.0.1", port=args.port, access_log=False, log_level="warning")
    return 0


def cmd_crypt_init(args: argparse.Namespace) -> int:
    """Create the encryption key pair; the secret key is protected by a new password."""
    try:
        first = read_passphrase("New password: ")
        if first != read_passphrase("Repeat password: "):
            print("ERROR: the passwords do not match", file=sys.stderr)
            return 1
        init_keys(args.data, first)
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"Key created in {args.data}. Remember the password: without it the encrypted files cannot be opened.")
    return 0


def cmd_crypt_add(args: argparse.Namespace) -> int:
    """Encrypt exports into the data directory. Needs no password (uses the public key)."""
    try:
        recipient = load_recipient(args.data)
        for name in args.files:
            source = Path(name)
            if source.suffix == ENCRYPTED_SUFFIX:
                raise ValueError(f"{source.name} is already encrypted")
            target = Path(args.data) / f"{source.name}{ENCRYPTED_SUFFIX}"
            if target.exists() and not args.force:
                raise ValueError(f"{target} already exists (use --force to replace it)")
            write_bytes_atomic(target, encrypt_bytes(source.read_bytes(), recipient))
            print(f"encrypted {source.name} -> {target}")
            if args.delete:
                source.unlink()
                print(f"removed {source}")
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    if not args.delete:
        print("The plain files are still there. Remove them yourself, or use --delete next time.")
    return 0


def cmd_crypt_private(args: argparse.Namespace) -> int:
    """Encrypt private.yaml into private.yaml.age."""
    try:
        source = Path(args.private)
        if not source.exists():
            raise ValueError(f"{source} not found")
        target = encrypted_path(source)
        if target.exists() and not args.force:
            raise ValueError(f"{target} already exists (use --force to replace it)")
        write_bytes_atomic(target, encrypt_bytes(source.read_bytes(), load_recipient(args.data)))
        print(f"encrypted {source.name} -> {target}")
        if args.delete:
            source.unlink()
            print(f"removed {source}")
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


def cmd_private(args: argparse.Namespace) -> int:
    """List, add or remove patterns of transactions to anonymize."""
    if args.action != "list" and not args.pattern:
        print(f"ERROR: `private {args.action}` needs a pattern", file=sys.stderr)
        return 2
    try:
        identity = unlock_with_prompt(args.data) if encrypted_path(args.private).exists() else None
        patterns = read_pattern_strings(args.private, identity)
        if args.action == "list":
            for pattern in patterns:
                print(pattern)
            return 0
        if args.action == "add":
            if args.pattern in patterns:
                print("already present")
                return 0
            patterns.append(args.pattern)
        else:
            if args.pattern not in patterns:
                print("ERROR: pattern not found", file=sys.stderr)
                return 1
            patterns.remove(args.pattern)
        written = write_pattern_strings(args.private, patterns, args.data)
        print(f"saved to {written}")
        if written.suffix != ENCRYPTED_SUFFIX and (Path(args.data) / "recipient.txt").exists():
            print("note: private.yaml is not encrypted; run `python -m budget crypt private --delete`")
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="budget", description="Personal budget from bank CSV exports")
    sub = parser.add_subparsers(dest="command", required=True)

    check = sub.add_parser("check", help="parse a CSOB CSV and print aggregate statistics only")
    check.add_argument("csv", help="path to a CSOB CSV export")
    check.set_defaults(func=cmd_check)

    report = sub.add_parser("report", help="monthly summary with uncategorized transactions")
    report.add_argument("--month", required=True, help="month as YYYY-MM")
    report.add_argument("--data", default="data", help="directory with CSV exports (default: data)")
    report.add_argument("--rules", default="rules.yaml", help="categorization rules (default: rules.yaml)")
    report.add_argument(
        "--private", default="private.yaml", help="patterns of transactions to anonymize (default: private.yaml)"
    )
    report.set_defaults(func=cmd_report)

    cps = sub.add_parser("counterparties", help="unique counterparties with counts (no amounts), anonymized")
    cps.add_argument("--month", help="limit to month YYYY-MM (default: all data)")
    cps.add_argument("--data", default="data", help="directory with CSV exports (default: data)")
    cps.add_argument("--private", default="private.yaml", help="patterns to anonymize (default: private.yaml)")
    cps.add_argument(
        "--exclude-type",
        action="append",
        help="skip a transaction type, e.g. person-to-person payments (repeatable)",
    )
    cps.set_defaults(func=cmd_counterparties)

    crypt = sub.add_parser("crypt", help="encrypt exports and private.yaml with a password")
    crypt_sub = crypt.add_subparsers(dest="crypt_command", required=True)

    def add_data(p: argparse.ArgumentParser) -> None:
        p.add_argument("--data", default="data", help="directory with the exports and the key (default: data)")

    init = crypt_sub.add_parser("init", help="create the key (asks for a new password)")
    add_data(init)
    init.set_defaults(func=cmd_crypt_init)

    add = crypt_sub.add_parser("add", help="encrypt CSV exports into the data directory")
    add.add_argument("files", nargs="+", help="CSV files to encrypt")
    add.add_argument("--delete", action="store_true", help="remove the plain file after encrypting")
    add.add_argument("--force", action="store_true", help="replace an existing encrypted file")
    add_data(add)
    add.set_defaults(func=cmd_crypt_add)

    enc_private = crypt_sub.add_parser("private", help="encrypt private.yaml")
    enc_private.add_argument("--private", default="private.yaml", help="file to encrypt (default: private.yaml)")
    enc_private.add_argument("--delete", action="store_true", help="remove the plain file after encrypting")
    enc_private.add_argument("--force", action="store_true", help="replace an existing private.yaml.age")
    add_data(enc_private)
    enc_private.set_defaults(func=cmd_crypt_private)

    private = sub.add_parser("private", help="list, add or remove anonymization patterns")
    private.add_argument("action", choices=["list", "add", "remove"])
    private.add_argument("pattern", nargs="?", help="regex to add or remove")
    private.add_argument("--private", default="private.yaml", help="patterns file (default: private.yaml)")
    add_data(private)
    private.set_defaults(func=cmd_private)

    ui = sub.add_parser("ui", help="local web UI on 127.0.0.1")
    ui.add_argument("--data", default="data", help="directory with CSV exports (default: data)")
    ui.add_argument("--rules", default="rules.yaml", help="categorization rules (default: rules.yaml)")
    ui.add_argument("--private", default="private.yaml", help="patterns to anonymize (default: private.yaml)")
    ui.add_argument("--budgets", default="budgets.yaml", help="monthly limits (default: budgets.yaml)")
    ui.add_argument("--port", type=int, default=8000, help="port (default: 8000)")
    ui.add_argument("--dev", action="store_true", help="API only, for use with the Vite dev server")
    ui.add_argument("--no-browser", action="store_true", help="do not open a browser")
    ui.set_defaults(func=cmd_ui)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
