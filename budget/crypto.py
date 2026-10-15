"""Encryption at rest for bank exports and private.yaml, using the age format (pyrage).

Layout inside the data directory:
    identity.age     secret key, encrypted with the user's password (scrypt, slow on purpose)
    recipient.txt    matching public key, plain text
    *.csv.age        exports encrypted to the public key
private.yaml.age sits next to private.yaml and is encrypted to the same public key.

Files are encrypted with the public key, so importing a new export needs no password;
reading anything needs the password once, after which the secret key stays in memory.
All files are standard age files: `age -d -i key file.age` works without this program.
"""

from pathlib import Path

import pyrage
from pyrage import passphrase as age_passphrase
from pyrage import x25519

from budget.fileio import write_bytes_atomic, write_text_atomic

ENCRYPTED_SUFFIX = ".age"
KEY_FILE = "identity.age"
RECIPIENT_FILE = "recipient.txt"
MIN_PASSPHRASE_LENGTH = 8


class WrongPassphrase(ValueError):
    """The password does not open the secret key."""


def encrypted_path(path: str | Path) -> Path:
    """The encrypted twin of a file: private.yaml -> private.yaml.age."""
    return Path(f"{path}{ENCRYPTED_SUFFIX}")


def init_keys(data_dir: str | Path, passphrase: str) -> None:
    """Create a key pair: the secret key is stored encrypted with `passphrase`."""
    data_dir = Path(data_dir)
    if (data_dir / KEY_FILE).exists():
        raise ValueError(f"{data_dir / KEY_FILE} already exists; refusing to overwrite the key")
    if len(passphrase) < MIN_PASSPHRASE_LENGTH:
        raise ValueError(f"password must have at least {MIN_PASSPHRASE_LENGTH} characters")
    data_dir.mkdir(parents=True, exist_ok=True)
    identity = x25519.Identity.generate()
    write_bytes_atomic(data_dir / KEY_FILE, age_passphrase.encrypt(str(identity).encode(), passphrase))
    write_text_atomic(data_dir / RECIPIENT_FILE, f"{identity.to_public()}\n")


def load_recipient(data_dir: str | Path) -> x25519.Recipient:
    """The public key, used to encrypt files. Needs no password."""
    path = Path(data_dir) / RECIPIENT_FILE
    if not path.exists():
        raise ValueError(f"no encryption key in {Path(data_dir)}; run: python -m budget crypt init")
    return x25519.Recipient.from_str(path.read_text(encoding="utf-8").strip())


def unlock(data_dir: str | Path, passphrase: str) -> x25519.Identity:
    """The secret key, opened with the password. Slow by design (about a second)."""
    path = Path(data_dir) / KEY_FILE
    if not path.exists():
        raise ValueError(f"no encryption key in {Path(data_dir)}; run: python -m budget crypt init")
    try:
        secret = age_passphrase.decrypt(path.read_bytes(), passphrase)
    except pyrage.DecryptError:
        raise WrongPassphrase("wrong password") from None
    return x25519.Identity.from_str(secret.decode())


def encrypt_bytes(data: bytes, recipient: x25519.Recipient) -> bytes:
    return pyrage.encrypt(data, [recipient])


def decrypt_bytes(data: bytes, identity: x25519.Identity, name: str) -> bytes:
    try:
        return pyrage.decrypt(data, [identity])
    except pyrage.DecryptError:
        raise ValueError(f"cannot decrypt {name}: damaged file or encrypted for a different key") from None


def read_maybe_encrypted(path: Path, identity: x25519.Identity | None) -> bytes:
    """File contents; files ending in .age are decrypted (which needs the unlocked key)."""
    raw = path.read_bytes()
    if path.suffix != ENCRYPTED_SUFFIX:
        return raw
    if identity is None:
        raise ValueError(f"{path.name} is encrypted: a password is required")
    return decrypt_bytes(raw, identity, path.name)


def needs_unlock(data_dir: str | Path, private_path: str | Path) -> bool:
    """True when any encrypted export or an encrypted private.yaml exists."""
    exports = (p for p in Path(data_dir).glob(f"*{ENCRYPTED_SUFFIX}") if p.name != KEY_FILE)
    return any(exports) or encrypted_path(private_path).exists()
