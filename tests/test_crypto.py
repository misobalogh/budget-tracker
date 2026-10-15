import shutil
import stat
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from pyrage import x25519

from budget.__main__ import main
from budget.api import create_app
from budget.crypto import (
    WrongPassphrase,
    encrypt_bytes,
    encrypted_path,
    init_keys,
    load_recipient,
    needs_unlock,
    unlock,
)
from budget.parsers.csob import parse_csob
from budget.privacy import PLACEHOLDER, load_private_patterns, read_pattern_strings, write_pattern_strings
from budget.report import load_transactions

FIXTURE = Path(__file__).parent / "fixtures" / "csob_sample.csv"
PASSWORD = "correct horse battery"
RULES = "groups: {sport: variable}\nrules:\n  - {category: sport, match: {counterparty: gym}}\n"


# Unlocking is slow on purpose (scrypt, ~1.5 s), so one key pair is made per test session.
@pytest.fixture(scope="session")
def key_template(tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("keys")
    init_keys(path, PASSWORD)
    return path


@pytest.fixture(scope="session")
def identity(key_template):
    return unlock(key_template, PASSWORD)


@pytest.fixture
def data(tmp_path: Path, key_template: Path) -> Path:
    path = tmp_path / "data"
    shutil.copytree(key_template, path)
    return path


@pytest.fixture
def fast_unlock(monkeypatch, identity):
    """CLI commands unlock with the session key instead of running scrypt again."""

    def fake_unlock(data_dir, passphrase):
        if passphrase != PASSWORD:
            raise WrongPassphrase("wrong password")
        return identity

    monkeypatch.setattr("budget.__main__.unlock", fake_unlock)


def encrypt_fixture(data: Path, name: str = "export.csv.age") -> Path:
    target = data / name
    target.write_bytes(encrypt_bytes(FIXTURE.read_bytes(), load_recipient(data)))
    return target


def passwords(monkeypatch, *answers: str):
    """Answer password prompts in order; running out of answers fails the test."""
    queue = list(answers)
    monkeypatch.setattr("budget.__main__.read_passphrase", lambda prompt: queue.pop(0))
    return queue


def test_key_pair_roundtrip_and_permissions(data, identity):
    assert stat.S_IMODE((data / "identity.age").stat().st_mode) == 0o600
    assert str(identity.to_public()) == str(load_recipient(data))
    assert b"AGE-SECRET-KEY" not in (data / "identity.age").read_bytes()


def test_wrong_password_and_missing_key(data, tmp_path):
    with pytest.raises(WrongPassphrase):
        unlock(data, "not the password")
    with pytest.raises(ValueError, match="no encryption key"):
        unlock(tmp_path / "empty", PASSWORD)
    with pytest.raises(ValueError, match="no encryption key"):
        load_recipient(tmp_path / "empty")


def test_init_refuses_to_overwrite_the_key_and_short_passwords(data, tmp_path):
    with pytest.raises(ValueError, match="refusing to overwrite"):
        init_keys(data, "another password")
    with pytest.raises(ValueError, match="at least 8"):
        init_keys(tmp_path / "other", "short")


def test_encrypted_export_parses_like_the_plain_one(data, identity):
    encrypted = encrypt_fixture(data)
    assert b"Example Employer" not in encrypted.read_bytes()
    pd.testing.assert_frame_equal(parse_csob(encrypted, identity), parse_csob(FIXTURE))
    with pytest.raises(ValueError, match="password is required"):
        parse_csob(encrypted)


def test_file_encrypted_for_another_key_gives_a_clear_error(data, identity):
    stranger = x25519.Identity.generate()
    encrypted = data / "export.csv.age"
    encrypted.write_bytes(encrypt_bytes(FIXTURE.read_bytes(), stranger.to_public()))
    with pytest.raises(ValueError, match="cannot decrypt export.csv.age"):
        parse_csob(encrypted, identity)


def test_load_transactions_mixes_plain_and_encrypted_and_deduplicates(data, identity):
    encrypt_fixture(data)
    assert len(load_transactions(data, identity)) == 6
    shutil.copy(FIXTURE, data / "plain.csv")
    assert len(load_transactions(data, identity)) == 6  # same transactions, counted once
    with pytest.raises(ValueError, match="password is required"):
        load_transactions(data)


def test_needs_unlock(data, tmp_path):
    private = tmp_path / "private.yaml"
    assert not needs_unlock(data, private)  # the key file alone is not an encrypted export
    shutil.copy(FIXTURE, data / "plain.csv")
    assert not needs_unlock(data, private)
    encrypt_fixture(data)
    assert needs_unlock(data, private)
    (data / "export.csv.age").unlink()
    encrypted_path(private).write_bytes(b"x")
    assert needs_unlock(data, private)


def test_private_patterns_are_stored_encrypted(data, identity, tmp_path):
    private = tmp_path / "private.yaml"
    written = write_pattern_strings(private, ["secret-site"], data)
    assert written == encrypted_path(private)
    assert not private.exists()
    assert b"secret-site" not in written.read_bytes()

    assert read_pattern_strings(private, identity) == ["secret-site"]
    assert [p.pattern for p in load_private_patterns(private, identity)] == ["secret-site"]
    with pytest.raises(ValueError, match="password is required"):
        load_private_patterns(private)
    with pytest.raises(ValueError, match="invalid regex"):
        write_pattern_strings(private, ["("], data)


def test_existing_plain_private_file_stays_plain_until_encrypted(data, tmp_path):
    private = tmp_path / "private.yaml"
    private.write_text("patterns:\n  - old\n")
    written = write_pattern_strings(private, ["old", "new"], data)
    assert written == private
    assert not encrypted_path(private).exists()


def test_cli_init_add_and_report_flow(tmp_path, monkeypatch, capsys):
    data = tmp_path / "data"
    source = tmp_path / "download.csv"
    shutil.copy(FIXTURE, source)
    rules = tmp_path / "rules.yaml"
    rules.write_text(RULES)

    passwords(monkeypatch, PASSWORD, "different")
    assert main(["crypt", "init", "--data", str(data)]) == 1
    assert "do not match" in capsys.readouterr().err
    passwords(monkeypatch, PASSWORD, PASSWORD)
    assert main(["crypt", "init", "--data", str(data)]) == 0

    assert main(["crypt", "add", str(source), "--data", str(data), "--delete"]) == 0  # no password needed
    assert not source.exists()
    assert (data / "download.csv.age").exists()
    assert main(["crypt", "add", str(data / "download.csv.age"), "--data", str(data)]) == 1  # already encrypted

    private = tmp_path / "private.yaml"
    report = ["report", "--month", "2026-09", "--data", str(data), "--rules", str(rules), "--private", str(private)]
    passwords(monkeypatch, "wrong", PASSWORD)  # a typo is forgiven
    assert main(report) == 0
    out = capsys.readouterr()
    assert "Wrong password." in out.err
    assert "balance" in out.out and "Shop One" in out.out


def test_cli_gives_up_after_three_wrong_passwords(fast_unlock, data, tmp_path, monkeypatch, capsys):
    encrypt_fixture(data)
    rules = tmp_path / "rules.yaml"
    rules.write_text(RULES)
    queue = passwords(monkeypatch, "a", "b", "c", "d")
    args = ["report", "--month", "2026-09", "--data", str(data), "--rules", str(rules), "--private", str(tmp_path / "p.yaml")]
    assert main(args) == 1
    assert "too many wrong passwords" in capsys.readouterr().err
    assert queue == ["d"]


def test_cli_private_commands_and_encrypting_an_existing_file(fast_unlock, data, tmp_path, monkeypatch, capsys):
    private = tmp_path / "private.yaml"
    private.write_text("patterns:\n  - plain-one\n")
    base = ["--data", str(data), "--private", str(private)]

    assert main(["crypt", "private", "--delete", *base]) == 0
    assert not private.exists() and encrypted_path(private).exists()
    assert main(["crypt", "private", *base]) == 1  # nothing left to encrypt

    passwords(monkeypatch, PASSWORD, PASSWORD, PASSWORD, PASSWORD)
    assert main(["private", "add", "second", *base]) == 0
    assert main(["private", "add", "second", *base]) == 0
    assert "already present" in capsys.readouterr().out
    assert main(["private", "list", *base]) == 0
    assert capsys.readouterr().out.split() == ["plain-one", "second"]
    assert main(["private", "remove", "plain-one", *base]) == 0
    assert read_pattern_strings(private, unlock(data, PASSWORD)) == ["second"]
    assert not private.exists()
    assert main(["private", "add", *base]) == 2


def test_cli_check_reads_an_encrypted_export(fast_unlock, data, monkeypatch, capsys):
    encrypted = encrypt_fixture(data)
    passwords(monkeypatch, PASSWORD)
    assert main(["check", str(encrypted)]) == 0
    out = capsys.readouterr().out
    assert "rows: 6" in out and "Example Employer" not in out


def test_api_serves_encrypted_data_without_leaking_private_names(data, identity, tmp_path):
    encrypt_fixture(data)
    rules = tmp_path / "rules.yaml"
    rules.write_text(RULES)
    private = tmp_path / "private.yaml"
    write_pattern_strings(private, ["shop one"], data)

    app = create_app(data, rules, private, budgets_path=tmp_path / "b.yaml", identity=identity)
    client = TestClient(app, base_url="http://127.0.0.1")
    body = client.get("/api/transactions").text
    assert "Shop One" not in body and PLACEHOLDER in body
    assert client.post("/api/reload").json()["count"] == 6
