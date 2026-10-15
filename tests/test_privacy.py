import re
import shutil
from pathlib import Path

import pandas as pd
import pytest

from budget.__main__ import main
from budget.privacy import PLACEHOLDER, anonymize, load_private_patterns

FIXTURE = Path(__file__).parent / "fixtures" / "csob_sample.csv"


def frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-09-01", "2026-09-02"]),
            "amount": [-14.97, -5.0],
            "counterparty": ["PAY*secret-site.example", "Shop"],
            "message": ["Suma: 16,99 USD Miesto: PAY*secret-site.example", "Miesto: Shop"],
            "raw_category": ["Platba kartou", "Platba kartou"],
        }
    )


def test_anonymize_masks_matching_rows_only():
    out = anonymize(frame(), [re.compile("SECRET-site", re.IGNORECASE)])
    assert out.loc[0, "counterparty"] == PLACEHOLDER
    assert out.loc[0, "message"] == PLACEHOLDER
    assert out.loc[0, "amount"] == -14.97
    assert out.loc[0, "raw_category"] == "Platba kartou"
    assert out.loc[1, "counterparty"] == "Shop"


def test_anonymize_matches_message_too():
    df = frame()
    df.loc[0, "counterparty"] = "Generic Processor"
    out = anonymize(df, [re.compile("secret-site", re.IGNORECASE)])
    assert out.loc[0, "counterparty"] == PLACEHOLDER


def test_anonymize_does_not_modify_input():
    df = frame()
    anonymize(df, [re.compile("secret")])
    assert df.loc[0, "counterparty"] == "PAY*secret-site.example"


def test_missing_file_means_no_patterns(tmp_path):
    assert load_private_patterns(tmp_path / "none.yaml") == []


def test_invalid_pattern_raises(tmp_path):
    path = tmp_path / "private.yaml"
    path.write_text("patterns:\n  - '('\n")
    with pytest.raises(ValueError, match="invalid regex"):
        load_private_patterns(path)


def test_cli_report_hides_private_transactions(tmp_path, capsys):
    data = tmp_path / "data"
    data.mkdir()
    shutil.copy(FIXTURE, data / "export.csv")
    rules = tmp_path / "rules.yaml"
    rules.write_text("groups: {}\nrules: []\n")
    private = tmp_path / "private.yaml"
    private.write_text("patterns:\n  - 'shop one'\n")

    args = ["report", "--month", "2026-09", "--data", str(data), "--rules", str(rules), "--private", str(private)]
    assert main(args) == 0
    out = capsys.readouterr().out
    assert "Shop One" not in out
    assert PLACEHOLDER in out
    assert "balance        1771.70" in out
