"""Pipeline orchestrator — runs the full medallion ETL end-to-end.

Stage order:
  1. Bronze ingest (CSV → Parquet, contract validation)
  2. DQ checks + quarantine
  3. Silver dimensions
  4. Silver facts
  5. Gold materialisations
  6. Permission enforcement
  7. Audit log write
"""

from __future__ import annotations

import json
import logging
import os
import stat
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import yaml

from src.ingest.bronze_loader import (
    ContractBreachError,
    load_all_bronze,
    validate_contract_definition,
)
from src.transform.dq_checks import run_all_checks
from src.transform.dimensions import (
    build_dim_department,
    build_dim_employee,
    build_dim_job,
    build_dim_location,
)
from src.transform.facts import build_fact_absence, build_fact_hr_tickets
from src.transform.governance import load_hmac_secret
from src.serve.gold_views import (
    build_absence_rate_by_job_family,
    build_headcount_by_department,
    build_open_tickets_summary,
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

_DIR_PERMISSIONS: dict[str, int] = {
    "bronze": 0o700,
    "silver/restricted": 0o700,
    "silver/internal": 0o750,
    "gold": 0o755,
    "quarantine": 0o700,
}


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------

def _write_parquet(df: pd.DataFrame, path: Path) -> None:
    """Atomic write: write to .tmp then rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".parquet.tmp")
    pq.write_table(pa.Table.from_pandas(df, preserve_index=False), tmp)
    tmp.rename(path)


def _write_audit(run_id: str, started_at: str, payload: dict) -> None:
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    ts = started_at[:19].replace(":", "").replace("-", "").replace("T", "T")
    path = AUDIT_DIR / f"run_{ts}.json"
    entry = {"run_id": run_id, "started_at": started_at, **payload}
    path.write_text(json.dumps(entry, indent=2, default=str))
    logger.info("Audit log written: %s", path.name)


# ---------------------------------------------------------------------------
# Config & secret
# ---------------------------------------------------------------------------

def _load_config() -> tuple[dict, dict]:
    contracts = yaml.safe_load((CONFIG_DIR / "data_contracts.yaml").read_text())
    dq_rules = yaml.safe_load((CONFIG_DIR / "dq_rules.yaml").read_text())
    return contracts, dq_rules


# ---------------------------------------------------------------------------
# Pipeline stages
# ---------------------------------------------------------------------------

def _stage1_bronze(contracts: dict) -> tuple[dict, dict]:
    logger.info("Stage 1: Bronze ingest — start")
    bronze_dfs, bronze_audit = load_all_bronze(DATA_DIR, OUTPUT_DIR, contracts)
    total_rows = sum(bronze_audit["row_counts"].values())
    logger.info(
        "Stage 1: Bronze ingest — complete (%d tables, %d rows)",
        bronze_audit["tables_loaded"], total_rows,
    )
    return bronze_dfs, bronze_audit


def _stage2_dq(bronze_dfs: dict, dq_rules: dict) -> tuple[dict, dict]:
    logger.info("Stage 2: DQ checks — start")
    clean_dfs, quarantine_dfs = run_all_checks(
        bronze_dfs, dq_rules, OUTPUT_DIR / "quarantine"
    )
    total_q = sum(len(v) for v in quarantine_dfs.values())
    logger.info(
        "Stage 2: DQ checks — complete (%d quarantine rows across %d tables)",
        total_q, len(quarantine_dfs),
    )
    return clean_dfs, quarantine_dfs


def _stage3_silver_dims(
    clean_dfs: dict, contracts: dict, secret: bytes
) -> dict[str, Path]:
    """Build and write all four dimensions; return paths for downstream use."""
    logger.info("Stage 3: Silver dimensions — start")
    internal = OUTPUT_DIR / "silver" / "internal"
    restricted = OUTPUT_DIR / "silver" / "restricted"

    dim_emp_int, dim_emp_res = build_dim_employee(
        clean_dfs["successfactors/employees"],
        clean_dfs["successfactors/employee_job"],
        clean_dfs.get("successfactors/employee_personal", pd.DataFrame()),
        contracts, secret,
    )
    _write_parquet(dim_emp_int, internal / "dim_employee.parquet")
    _write_parquet(dim_emp_res, restricted / "dim_employee.parquet")

    dim_dept = build_dim_department(clean_dfs["successfactors/departments"], contracts)
    _write_parquet(dim_dept, internal / "dim_department.parquet")

    dim_job = build_dim_job(clean_dfs["successfactors/job_codes"], contracts)
    _write_parquet(dim_job, internal / "dim_job.parquet")

    dim_loc = build_dim_location(clean_dfs["successfactors/locations"], contracts)
    _write_parquet(dim_loc, internal / "dim_location.parquet")

    logger.info("Stage 3: Silver dimensions — complete (4 dims written)")
    return {
        "dim_employee": internal / "dim_employee.parquet",
        "dim_department": internal / "dim_department.parquet",
        "dim_job": internal / "dim_job.parquet",
        "dim_location": internal / "dim_location.parquet",
    }


def _stage4_silver_facts(
    clean_dfs: dict,
    dim_employee: pd.DataFrame,
    dq_rules: dict,
    contracts: dict,
    secret: bytes,
) -> dict[str, Path]:
    """Build and write fact tables; return paths for downstream use."""
    logger.info("Stage 4: Silver facts — start")
    internal = OUTPUT_DIR / "silver" / "internal"
    sensitive_ids = dq_rules.get("sensitive_absence_type_ids", [])

    fact_abs = build_fact_absence(
        clean_dfs.get("atoss/absence_requests", pd.DataFrame()),
        dim_employee, sensitive_ids,
    )
    _write_parquet(fact_abs, internal / "fact_absence.parquet")

    fact_tkt = build_fact_hr_tickets(
        clean_dfs.get("servicenow/tickets", pd.DataFrame()),
        clean_dfs.get("servicenow/ticket_comments", pd.DataFrame()),
        clean_dfs.get("servicenow/ticket_categories", pd.DataFrame()),
        dim_employee, contracts, secret,
    )
    _write_parquet(fact_tkt, internal / "fact_hr_tickets.parquet")

    logger.info("Stage 4: Silver facts — complete (2 facts written)")
    return {
        "fact_absence": internal / "fact_absence.parquet",
        "fact_hr_tickets": internal / "fact_hr_tickets.parquet",
    }


def _stage5_gold(dim_paths: dict[str, Path], fact_paths: dict[str, Path]) -> list[str]:
    """Build and write gold aggregations from silver Parquet files."""
    logger.info("Stage 5: Gold materialisations — start")
    gold = OUTPUT_DIR / "gold"
    gold.mkdir(parents=True, exist_ok=True)
    materialised: list[str] = []

    headcount = build_headcount_by_department(
        dim_paths["dim_employee"], dim_paths["dim_department"]
    )
    _write_parquet(headcount, gold / "headcount_by_department.parquet")
    materialised.append("headcount_by_department")

    if fact_paths["fact_absence"].exists():
        absence_rate = build_absence_rate_by_job_family(
            fact_paths["fact_absence"],
            dim_paths["dim_employee"],
            dim_paths["dim_job"],
        )
        _write_parquet(absence_rate, gold / "absence_rate_by_job_family.parquet")
        materialised.append("absence_rate_by_job_family")

    if fact_paths["fact_hr_tickets"].exists():
        tickets_summary = build_open_tickets_summary(
            fact_paths["fact_hr_tickets"],
            dim_paths["dim_department"],
        )
        _write_parquet(tickets_summary, gold / "open_tickets_summary.parquet")
        materialised.append("open_tickets_summary")

    logger.info("Stage 5: Gold — complete (%d views materialised)", len(materialised))
    return materialised


def _stage6_permissions() -> None:
    """Enforce directory permissions per governance access control rules."""
    for rel_path, mode in _DIR_PERMISSIONS.items():
        path = OUTPUT_DIR / rel_path
        if path.exists():
            path.chmod(mode)
    logger.info("Stage 6: Permissions enforced")


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Run the full pipeline end-to-end."""
    run_id = str(uuid.uuid4())
    started_at = datetime.now(tz=timezone.utc).isoformat()
    audit: dict = {"status": "running"}

    try:
        logger.info("Pipeline starting — run_id=%s", run_id)

        contracts, dq_rules = _load_config()
        validate_contract_definition(contracts)
        secret = load_hmac_secret()

        bronze_dfs, bronze_audit = _stage1_bronze(contracts)
        audit["bronze"] = bronze_audit

        clean_dfs, quarantine_dfs = _stage2_dq(bronze_dfs, dq_rules)
        audit["dq"] = {
            "tables_with_quarantine": list(quarantine_dfs.keys()),
            "total_quarantine_rows": sum(len(v) for v in quarantine_dfs.values()),
        }

        dim_paths = _stage3_silver_dims(clean_dfs, contracts, secret)
        dim_employee = pd.read_parquet(dim_paths["dim_employee"])

        fact_paths = _stage4_silver_facts(clean_dfs, dim_employee, dq_rules, contracts, secret)

        gold_views = _stage5_gold(dim_paths, fact_paths)
        audit["gold"] = {"views_materialised": gold_views}

        _stage6_permissions()

        audit["status"] = "success"
        audit["completed_at"] = datetime.now(tz=timezone.utc).isoformat()
        logger.info("Pipeline complete — run_id=%s", run_id)

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
