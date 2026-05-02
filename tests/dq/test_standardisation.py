import pandas as pd
import pytest

from src.transform.dq_checks import check_dq22_gender_standardisation


def _make_personal(genders: list) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "employee_id": [f"EMP{i:03d}" for i in range(len(genders))],
            "gender": genders,
        }
    )


def test_dq22_male_standardised_to_m():
    df = _make_personal(["Male"])
    clean, quarantine = check_dq22_gender_standardisation(df)
    assert quarantine.empty
    assert clean.iloc[0]["gender"] == "M"


def test_dq22_female_standardised_to_f():
    df = _make_personal(["Female"])
    clean, quarantine = check_dq22_gender_standardisation(df)
    assert quarantine.empty
    assert clean.iloc[0]["gender"] == "F"


def test_dq22_blank_standardised_to_unknown():
    df = _make_personal([""])
    clean, quarantine = check_dq22_gender_standardisation(df)
    assert quarantine.empty
    assert clean.iloc[0]["gender"] == "Unknown"


def test_dq22_null_standardised_to_unknown():
    df = _make_personal([None])
    clean, quarantine = check_dq22_gender_standardisation(df)
    assert quarantine.empty
    assert clean.iloc[0]["gender"] == "Unknown"


def test_dq22_valid_codes_unchanged():
    for code in ["M", "F", "X", "Unknown"]:
        df = _make_personal([code])
        clean, _ = check_dq22_gender_standardisation(df)
        assert clean.iloc[0]["gender"] == code


def test_dq22_lowercase_standardised():
    df = _make_personal(["male", "female"])
    clean, _ = check_dq22_gender_standardisation(df)
    assert clean.iloc[0]["gender"] == "M"
    assert clean.iloc[1]["gender"] == "F"


def test_dq22_no_rows_quarantined():
    df = _make_personal(["Male", "Female", "X", "", None, "Unknown"])
    clean, quarantine = check_dq22_gender_standardisation(df)
    assert quarantine.empty
    assert len(clean) == len(df)
