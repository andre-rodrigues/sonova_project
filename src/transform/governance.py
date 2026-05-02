import hashlib
import hmac
import logging
import os
import re

import pandas as pd

logger = logging.getLogger(__name__)

# Compiled once at module load — never log matched values
_REDACTION_PATTERNS = [
    re.compile(r"\b756\.\d{4}\.\d{4}\.\d{2}\b"),                          # Swiss AHV
    re.compile(r"\b[A-Z]{2}\d{6}[A-D]\b"),                                # UK NI
    re.compile(r"\b[12]\d{2}(?:0[1-9]|1[0-2])\d{5}\d{3}\d{2}\b"),        # French SSN
    re.compile(r"\b[\w.+-]+@[\w-]+\.[a-zA-Z]{2,}\b"),                     # Email
    re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{4}\d{7}[A-Z0-9]{0,16}\b"),      # IBAN
    re.compile(r"\bINS-[A-Z0-9]{4}-[A-Z0-9]{5}\b"),                       # Insurance ref
    re.compile(r"\b\d{3,8}-\d{5,12}\b"),                                   # Bank account
]


def load_hmac_secret() -> bytes:
    raw = os.environ.get("PIPELINE_HMAC_SECRET", "")
    if not raw:
        raise EnvironmentError("PIPELINE_HMAC_SECRET environment variable is not set or empty")
    logger.info("HMAC secret loaded (fingerprint: %s)", raw[:4])
    return raw.encode("utf-8")


def pseudonymise(value: str, secret: bytes) -> str:
    return hmac.new(secret, value.encode("utf-8"), hashlib.sha256).hexdigest()[:16]


def redact_free_text(text: str) -> tuple[str, int]:
    if not isinstance(text, str):
        return text, 0
    count = 0
    for pattern in _REDACTION_PATTERNS:
        new_text, n = pattern.subn("[REDACTED]", text)
        count += n
        text = new_text
    return text, count


def apply_field_classification(
    df: pd.DataFrame,
    table_key: str,
    contracts: dict,
    secret: bytes,
    layer: str,
) -> pd.DataFrame:
    """Apply governance treatments based on PII tier and layer.

    For internal layer: PII-SC and PII-S fields are excluded entirely; DOB is
    generalised to birth_year; free-text PII fields are redacted.
    For restricted layer: PII-S fields are pseudonymised; PII-SC fields are
    excluded (Art. 9 — never stored); free-text fields are redacted.
    """
    system, table = table_key.split("/", 1)
    table_contract = contracts[system][table]
    df = df.copy()

    for col, spec in table_contract.items():
        if col.startswith("_contract"):
            continue
        if col not in df.columns:
            continue

        treatment = spec.get("treatment")
        tier = spec.get("tier")

        if tier in ("PII-SC", "PII-S") and layer == "internal":
            # These fields must never appear in silver/internal regardless of treatment
            df = df.drop(columns=[col])
            continue

        if tier == "PII-SC" and layer == "restricted":
            # Special-category data excluded from all machine-readable outputs
            df = df.drop(columns=[col])
            continue

        if treatment == "pseudonymise":
            df[col] = df[col].apply(
                lambda v, s=secret: pseudonymise(str(v), s) if pd.notna(v) else v
            )
        elif treatment == "generalise_to_year":
            new_col = col.replace("date_of_birth", "birth_year") if "date_of_birth" in col else col + "_year"
            df[new_col] = pd.to_datetime(df[col], errors="coerce").dt.year.astype("Int64")
            df = df.drop(columns=[col])
        elif treatment == "redact":
            total = 0

            def _redact(v, _total=None):
                nonlocal total
                if not isinstance(v, str):
                    return v
                redacted, n = redact_free_text(v)
                total += n
                return redacted

            df[col] = df[col].apply(_redact)
            logger.info("Redacted %d occurrences in %s.%s", total, table_key, col)

    return df


def validate_manifest_coverage(
    df: pd.DataFrame,
    table_key: str,
    contracts: dict,
) -> None:
    system, table = table_key.split("/", 1)
    table_contract = contracts[system][table]
    declared = {k for k in table_contract if not k.startswith("_contract")}
    exempt = {"_ingested_at", "_source_file"}
    undeclared = set(df.columns) - declared - exempt
    if undeclared:
        raise ValueError(f"Undeclared columns in {table_key}: {undeclared}")
