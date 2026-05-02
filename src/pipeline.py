from __future__ import annotations

import json
import logging
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import yaml

from src.ingest.bronze_loader import (
    ContractBreachError,
    load_all_bronze,
    validate_contract_definition,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
OUTPUT_DIR = ROOT / "output"
AUDIT_DIR = ROOT / "audit"
CONFIG_DIR = ROOT / "config"


# ---------------------------------------------------------------------------
# Config & secret loading
# ---------------------------------------------------------------------------

def _load_config() -> tuple[dict, dict]:
    contracts = yaml.safe_load((CONFIG_DIR / "data_contracts.yaml").read_text())
    dq_rules = yaml.safe_load((CONFIG_DIR / "dq_rules.yaml").read_text())
    return contracts, dq_rules


def _load_hmac_secret() -> bytes:
    secret = os.environ.get("PIPELINE_HMAC_SECRET", "")
    if not secret:
        raise EnvironmentError(
            "PIPELINE_HMAC_SECRET environment variable is not set. "
            "Export it before running the pipeline."
        )
    logger.info("HMAC secret fingerprint: %s...", secret[:4])
    return secret.encode()


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------

def _write_audit(run_id: str, started_at: str, payload: dict) -> None:
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    ts = started_at[:19].replace(":", "").replace("-", "").replace("T", "T")
    path = AUDIT_DIR / f"run_{ts}.json"
    entry = {"run_id": run_id, "started_at": started_at, **payload}
    path.write_text(json.dumps(entry, indent=2, default=str))
    logger.info("Audit log written: %s", path.name)


# ---------------------------------------------------------------------------
# Pipeline stages
# ---------------------------------------------------------------------------

def _stage1_bronze(contracts: dict) -> tuple[dict, dict]:
    logger.info("Stage 1: Bronze ingest — start")
    bronze_dfs, bronze_audit = load_all_bronze(DATA_DIR, OUTPUT_DIR, contracts)
    total_rows = sum(bronze_audit["row_counts"].values())
    logger.info(
        "Stage 1: Bronze ingest — complete (%d tables, %d rows)",
        bronze_audit["tables_loaded"],
        total_rows,
    )
    return bronze_dfs, bronze_audit


def _stage2_dq(bronze_dfs: dict, dq_rules: dict) -> dict:
    # Phase 4 not yet implemented — run_all_checks lives in src/transform/dq_checks.py
    logger.info("Stage 2: DQ checks — not yet implemented (Phase 4 pending)")
    return bronze_dfs  # pass-through until DQ is wired up


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def main() -> None:
    run_id = str(uuid.uuid4())
    started_at = datetime.now(tz=timezone.utc).isoformat()
    audit: dict = {"status": "running", "bronze": {}}

    try:
        logger.info("Pipeline starting — run_id=%s", run_id)

        contracts, dq_rules = _load_config()
        validate_contract_definition(contracts)
        logger.info("Contract definition validated")

        secret = _load_hmac_secret()

        # Stage 1 — Bronze ingest
        bronze_dfs, bronze_audit = _stage1_bronze(contracts)
        audit["bronze"] = bronze_audit

        # Stage 2 — DQ checks + quarantine
        clean_dfs = _stage2_dq(bronze_dfs, dq_rules)

        # Stages 3–7 pending (Phases 3–7)
        logger.info("Stages 3–7 not yet implemented")

        audit["status"] = "success"
        audit["completed_at"] = datetime.now(tz=timezone.utc).isoformat()
        logger.info("Pipeline complete")

    except (ContractBreachError, EnvironmentError) as exc:
        audit["status"] = "failed"
        audit["error_detail"] = str(exc)
        audit["completed_at"] = datetime.now(tz=timezone.utc).isoformat()
        logger.error("Pipeline failed: %s", exc)
        _write_audit(run_id, started_at, audit)
        sys.exit(1)

    except Exception as exc:
        audit["status"] = "failed"
        audit["error_detail"] = str(exc)
        audit["completed_at"] = datetime.now(tz=timezone.utc).isoformat()
        logger.error("Unexpected pipeline error", exc_info=True)
        _write_audit(run_id, started_at, audit)
        raise

    _write_audit(run_id, started_at, audit)


if __name__ == "__main__":
    main()
