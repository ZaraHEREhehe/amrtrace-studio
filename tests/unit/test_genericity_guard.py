"""Tests for the Z-15 genericity guard."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "check_genericity.py"


def run_guard(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def make_source_root(tmp_path: Path) -> Path:
    root = tmp_path / "amrtrace"
    (root / "evaluator").mkdir(parents=True)
    return root


def test_current_engine_passes():
    result = run_guard()

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Genericity guard passed" in result.stdout


def test_deliberate_violation_fails(tmp_path):
    root = make_source_root(tmp_path)

    (root / "evaluator" / "bad.py").write_text(
        'STANDARD_VERSION = "CLSI_M100_ED32"\n',
        encoding="utf-8",
    )

    result = run_guard("--source-root", str(root))

    assert result.returncode == 1
    assert "GENERICITY GUARD FAILED" in result.stderr
    assert "CLSI" in result.stderr
    assert "Ed32" in result.stderr


def test_short_scenario_names_use_boundaries(tmp_path):
    root = make_source_root(tmp_path)
    source = root / "evaluator" / "boundary.py"

    source.write_text(
        'FIRST = "ABC7X"\nSECOND = "C70"\n',
        encoding="utf-8",
    )

    clean = run_guard("--source-root", str(root))
    assert clean.returncode == 0, clean.stdout + clean.stderr

    source.write_text(
        'FIRST = "ABC7X"\nSECOND = "C70"\nSCENARIO = "C7"\n',
        encoding="utf-8",
    )

    violated = run_guard("--source-root", str(root))

    assert violated.returncode == 1
    assert "forbidden term 'C7'" in violated.stderr
