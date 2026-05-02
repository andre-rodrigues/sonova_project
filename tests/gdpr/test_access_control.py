import os
import stat
from pathlib import Path

import pytest


def _get_mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def _check_dir(tmp_path: Path, dirname: str, expected_mode: int) -> Path:
    d = tmp_path / dirname
    d.mkdir(parents=True)
    os.chmod(d, expected_mode)
    return d


def test_bronze_dir_owner_only(tmp_path):
    bronze = _check_dir(tmp_path, "bronze", 0o700)
    mode = _get_mode(bronze)
    assert mode & 0o077 == 0, f"bronze should not be accessible to group/other, got {oct(mode)}"


def test_silver_restricted_dir_owner_only(tmp_path):
    restricted = _check_dir(tmp_path, "silver/restricted", 0o700)
    mode = _get_mode(restricted)
    assert mode & 0o077 == 0, f"silver/restricted should not be accessible to group/other, got {oct(mode)}"


def test_silver_internal_dir_group_readable(tmp_path):
    internal = _check_dir(tmp_path, "silver/internal", 0o750)
    mode = _get_mode(internal)
    assert mode & 0o040 != 0, f"silver/internal should be group-readable, got {oct(mode)}"
    assert mode & 0o007 == 0, f"silver/internal should not be other-accessible, got {oct(mode)}"


def test_gold_dir_group_and_other_readable(tmp_path):
    gold = _check_dir(tmp_path, "gold", 0o755)
    mode = _get_mode(gold)
    assert mode & 0o044 != 0, f"gold should be readable by group and other, got {oct(mode)}"


def test_quarantine_dir_owner_only(tmp_path):
    quarantine = _check_dir(tmp_path, "quarantine", 0o700)
    mode = _get_mode(quarantine)
    assert mode & 0o077 == 0, f"quarantine should not be accessible to group/other, got {oct(mode)}"
