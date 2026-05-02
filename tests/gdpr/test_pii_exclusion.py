import pandas as pd
import pytest
import yaml

from src.transform.governance import apply_field_classification, validate_manifest_coverage

# Minimal contract covering employee_personal PII fields
_SAMPLE_CONTRACTS = {
    "successfactors": {
        "employee_personal": {
            "_contract_version": "1.0.0",
            "employee_id": {"dtype": "str", "nullable": False, "unique": True, "tier": "IND", "treatment": "passthrough"},
            "first_name": {"dtype": "str", "nullable": False, "unique": False, "tier": "PII-S", "treatment": "exclude"},
            "last_name": {"dtype": "str", "nullable": False, "unique": False, "tier": "PII-S", "treatment": "exclude"},
            "date_of_birth": {"dtype": "date", "nullable": True, "unique": False, "tier": "PII", "treatment": "generalise_to_year"},
            "gender": {"dtype": "str", "nullable": True, "unique": False, "tier": "PII-SC", "treatment": "exclude"},
            "nationality": {"dtype": "str", "nullable": True, "unique": False, "tier": "PII-SC", "treatment": "exclude"},
            "marital_status": {"dtype": "str", "nullable": True, "unique": False, "tier": "PII-SC", "treatment": "exclude"},
            "national_id": {"dtype": "str", "nullable": True, "unique": False, "tier": "PII-S", "treatment": "pseudonymise"},
            "national_id_type": {"dtype": "str", "nullable": True, "unique": False, "tier": "PII-S", "treatment": "exclude"},
            "last_modified": {"dtype": "datetime", "nullable": False, "unique": False, "tier": "SAFE", "treatment": "passthrough"},
        }
    }
}

_PII_SC_FIELDS = ["gender", "nationality", "marital_status"]
_PII_S_FIELDS = ["first_name", "last_name", "national_id", "national_id_type"]


@pytest.fixture
def personal_df():
    return pd.DataFrame(
        {
            "employee_id": ["EMP001"],
            "first_name": ["Anna"],
            "last_name": ["Mueller"],
            "date_of_birth": pd.to_datetime(["1985-03-14"]),
            "gender": ["Female"],
            "nationality": ["Swiss"],
            "marital_status": ["Married"],
            "national_id": ["756.1234.5678.90"],
            "national_id_type": ["AHV"],
            "last_modified": pd.to_datetime(["2024-12-01"]),
        }
    )


@pytest.mark.parametrize("field", _PII_S_FIELDS + _PII_SC_FIELDS)
def test_pii_fields_absent_from_silver_internal(personal_df, hmac_secret, field):
    result = apply_field_classification(
        personal_df, "successfactors/employee_personal", _SAMPLE_CONTRACTS, hmac_secret, "internal"
    )
    assert field not in result.columns, f"PII field '{field}' must not appear in silver/internal"


@pytest.mark.parametrize("field", _PII_SC_FIELDS)
def test_pii_sc_fields_absent_from_restricted(personal_df, hmac_secret, field):
    result = apply_field_classification(
        personal_df, "successfactors/employee_personal", _SAMPLE_CONTRACTS, hmac_secret, "restricted"
    )
    assert field not in result.columns, f"PII-SC field '{field}' must not appear in restricted"


def test_safe_field_present_in_internal(personal_df, hmac_secret):
    result = apply_field_classification(
        personal_df, "successfactors/employee_personal", _SAMPLE_CONTRACTS, hmac_secret, "internal"
    )
    assert "employee_id" in result.columns
    assert "last_modified" in result.columns


def test_dob_generalised_to_birth_year_in_internal(personal_df, hmac_secret):
    result = apply_field_classification(
        personal_df, "successfactors/employee_personal", _SAMPLE_CONTRACTS, hmac_secret, "internal"
    )
    assert "date_of_birth" not in result.columns
    assert "birth_year" in result.columns
    assert result["birth_year"].iloc[0] == 1985


def test_pii_s_pseudonymised_in_restricted(personal_df, hmac_secret):
    result = apply_field_classification(
        personal_df, "successfactors/employee_personal", _SAMPLE_CONTRACTS, hmac_secret, "restricted"
    )
    # national_id should be pseudonymised (16 hex chars), not the raw value
    assert "national_id" in result.columns
    assert result["national_id"].iloc[0] != "756.1234.5678.90"
    assert len(result["national_id"].iloc[0]) == 16


def test_unknown_column_raises(hmac_secret):
    df = pd.DataFrame(
        {
            "employee_id": ["EMP001"],
            "undeclared_column": ["some_value"],
            "last_modified": pd.to_datetime(["2024-12-01"]),
        }
    )
    with pytest.raises(ValueError, match="Undeclared columns"):
        validate_manifest_coverage(df, "successfactors/employee_personal", _SAMPLE_CONTRACTS)


def test_ingested_at_exempt_from_coverage_check(hmac_secret):
    df = pd.DataFrame(
        {
            "employee_id": ["EMP001"],
            "first_name": ["Anna"],
            "last_name": ["Mueller"],
            "date_of_birth": pd.to_datetime(["1985-03-14"]),
            "gender": ["Female"],
            "nationality": ["Swiss"],
            "marital_status": ["Married"],
            "national_id": ["756.1234.5678.90"],
            "national_id_type": ["AHV"],
            "last_modified": pd.to_datetime(["2024-12-01"]),
            "_ingested_at": pd.to_datetime(["2024-12-01"]),
            "_source_file": ["successfactors/employee_personal.csv"],
        }
    )
    # Should not raise — _ingested_at and _source_file are exempt
    validate_manifest_coverage(df, "successfactors/employee_personal", _SAMPLE_CONTRACTS)
