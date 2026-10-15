from pathlib import Path

import pandas as pd
import pytest

from budget.__main__ import main
from budget.parsers import NORMALIZED_COLUMNS
from budget.parsers.csob import parse_csob

FIXTURE = Path(__file__).parent / "fixtures" / "csob_sample.csv"
HEADER = (
    "Pohyby na ucte c. SK0000000000000000000000 zo dna 04.10.2026,,,,,,,,,\n"
    ",,,,,,,,,\n"
    "datum zauctovania,suma,mena,referencia platitela,typ transakcie,cislo uctu protistrany,"
    "banka protistrany,nazov protistrany,informacia pre prijemcu,doplnujuce udaje\n"
)


def write_csv(tmp_path: Path, rows: str, encoding: str = "utf-8") -> Path:
    path = tmp_path / "export.csv"
    path.write_bytes((HEADER + rows).encode(encoding))
    return path


@pytest.fixture
def df() -> pd.DataFrame:
    return parse_csob(FIXTURE)


def test_columns_and_types(df):
    assert list(df.columns) == NORMALIZED_COLUMNS
    assert pd.api.types.is_datetime64_any_dtype(df["date"])
    assert pd.api.types.is_float_dtype(df["amount"])


def test_skips_preamble_and_empty_rows(df):
    assert len(df) == 6


def test_dates_without_leading_zeros(df):
    assert df.loc[0, "date"] == pd.Timestamp(2026, 9, 28)
    assert df.loc[3, "date"] == pd.Timestamp(2026, 9, 1)


def test_amount_signs(df):
    assert df.loc[0, "amount"] == -11.0
    assert df.loc[2, "amount"] == 2500.0
    assert df.loc[4, "amount"] == pytest.approx(-42.30)


def test_raw_category_is_transaction_type(df):
    assert df.loc[0, "raw_category"] == "Platba kartou"
    assert df.loc[3, "raw_category"] == "Trvaly prikaz"


def test_counterparty_from_name(df):
    assert df.loc[2, "counterparty"] == "Example Employer s.r.o."


def test_counterparty_falls_back_to_card_merchant(df):
    assert df.loc[0, "counterparty"] == "TEST GYM"
    assert df.loc[1, "counterparty"] == "Shop One, Branch 2"


def test_counterparty_falls_back_to_account(df):
    assert df.loc[4, "counterparty"] == "SK3300000000000000000003"
    assert df.loc[4, "message"] == ""


def test_message_joins_extra_info(df):
    assert df.loc[5, "message"] == "Obed | splatka za obed"
    assert df.loc[3, "message"] == "Najom september"


def test_cp1250_encoding(tmp_path):
    rows = "3.9.2026,-1.50,EUR,,Platba kartou,,,,\"Miesto: Pek\xe1re\u0148 \u010cervenej\",\n"
    df = parse_csob(write_csv(tmp_path, rows, encoding="cp1250"))
    assert df.loc[0, "counterparty"] == "Pek\xe1re\u0148 \u010cervenej"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("-11.00", -11.0), ('"-1 234,56"', -1234.56), ('"1.234,56"', 1234.56), ('"1,234.56"', 1234.56)],
)
def test_amount_formats(tmp_path, raw, expected):
    df = parse_csob(write_csv(tmp_path, f"3.9.2026,{raw},EUR,,Platba kartou,,,,,\n"))
    assert df.loc[0, "amount"] == pytest.approx(expected)


def test_invalid_date_raises_without_row_content(tmp_path):
    path = write_csv(tmp_path, "3.9.2026,-1.00,EUR,,X,,,,,\n2026-09-04,-1.00,EUR,,SECRET,,,,,\n")
    with pytest.raises(ValueError, match=r"invalid date in data row\(s\) 2") as exc:
        parse_csob(path)
    assert "SECRET" not in str(exc.value)


def test_invalid_amount_raises(tmp_path):
    with pytest.raises(ValueError, match="invalid amount in data row 1"):
        parse_csob(write_csv(tmp_path, "3.9.2026,abc,EUR,,X,,,,,\n"))


def test_missing_header_raises(tmp_path):
    path = tmp_path / "bad.csv"
    path.write_text("foo,bar\n1,2\n")
    with pytest.raises(ValueError, match="header row"):
        parse_csob(path)


def test_check_prints_aggregates_only(capsys):
    assert main(["check", str(FIXTURE)]) == 0
    out = capsys.readouterr().out
    assert "rows: 6" in out
    assert "date range: 2026-09-01 .. 2026-09-28" in out
    assert "Platba kartou" in out
    assert "TEST GYM" not in out
    assert "2500" not in out
