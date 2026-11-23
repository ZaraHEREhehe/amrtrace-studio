"""Z-28 deterministic canaries, with no Docker, database or network required."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "z28_demo_seed.py"
SPEC = importlib.util.spec_from_file_location("z28_demo_seed", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def make_fixture(tmp_path):
    for name in MODULE.EXPECTED_FILES:
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(("VALIDATION_SUCCESS: " + name).encode())
    lines = []
    for name in sorted(MODULE.EXPECTED_FILES):
        digest = hashlib.sha256((tmp_path / name).read_bytes()).hexdigest()
        lines.append(f"{digest}  {name}\n")
    (tmp_path / "sha256.txt").write_text("".join(lines), encoding="utf-8")
    (tmp_path / "fixture_metadata.json").write_text(
        json.dumps({"total_cases": 660, "fixture_version": "Z14_MINI_COHORT_V1"}), encoding="utf-8")
    return tmp_path


def test_correct_committed_fixture_succeeds(tmp_path):
    fixture = make_fixture(tmp_path)
    assert MODULE.verify_fixture(fixture)["total_cases"] == 660


@pytest.mark.parametrize("mutation", ["corrupt_data", "bad_manifest", "missing_file", "wrong_count", "traversal"])
def test_fixture_tampering_is_rejected_before_seeding(tmp_path, mutation):
    fixture = make_fixture(tmp_path)
    if mutation == "corrupt_data":
        (fixture / sorted(MODULE.EXPECTED_FILES)[0]).write_bytes(b"tampered")
    elif mutation == "bad_manifest":
        (fixture / "sha256.txt").write_text("bad manifest\n")
    elif mutation == "missing_file":
        (fixture / sorted(MODULE.EXPECTED_FILES)[0]).unlink()
    elif mutation == "wrong_count":
        (fixture / "fixture_metadata.json").write_text(json.dumps({"total_cases": 10}))
    else:
        (fixture / "sha256.txt").write_text("a" * 64 + "  ../unsafe.txt\n")
    with pytest.raises((RuntimeError, FileNotFoundError)):
        MODULE.verify_fixture(fixture)


@pytest.mark.parametrize("cases,states,releases,action", [
    (0, 0, (), "seed"),
    (660, 660, (("R1", "PUBLISHED"),), "reuse"),
])
def test_only_empty_or_exact_r1_baseline_is_accepted(cases, states, releases, action):
    assert MODULE.decide_action(cases, states, releases) == action


@pytest.mark.parametrize("cases,states,releases", [
    (660, 0, ()), (0, 0, (("R1", "DRAFT"),)),
    (660, 659, (("R1", "PUBLISHED"),)),
    (660, 660, (("R1", "DRAFT"),)),
    (660, 660, (("R1", "PUBLISHED"), ("R2", "PUBLISHED"))),
    (41858, 41858, (("R1", "PUBLISHED"),)),
])
def test_partial_or_real_cohort_is_never_automatically_reseeded(cases, states, releases):
    with pytest.raises(RuntimeError, match="Z28_REFUSED"):
        MODULE.decide_action(cases, states, releases)


def test_compose_isolated_and_has_correct_dependency_graph():
    config = yaml.safe_load((ROOT / "deploy/demo/compose.yml").read_text(encoding="utf-8"))
    assert config["name"] == "amrtrace-z28-demo"
    services = config["services"]
    assert list(services) == ["db", "migrate", "seed", "api", "web"]
    assert services["migrate"]["depends_on"]["db"]["condition"] == "service_healthy"
    assert services["seed"]["depends_on"]["migrate"]["condition"] == "service_completed_successfully"
    assert services["api"]["depends_on"]["seed"]["condition"] == "service_completed_successfully"
    assert services["web"]["depends_on"]["api"]["condition"] == "service_healthy"
    assert not services["db"].get("ports")
    assert all("container_name" not in v for v in services.values())
    assert services["db"]["volumes"] == ["z28_pgdata:/var/lib/postgresql/data"]
    assert services["db"]["image"] == "postgres:16.10-alpine3.22"
    assert services["api"]["ports"] == ["127.0.0.1:${Z28_API_PORT:-18000}:8000"]
    assert services["web"]["ports"] == ["127.0.0.1:${Z28_WEB_PORT:-18080}:80"]
    for name in ("seed", "api"):
        env = services[name]["environment"]
        assert all(env[key] == "" for key in (
            "GROQ_API_KEY", "AMRTRACE_COPILOT_LOCAL_MODEL", "AMRTRACE_COPILOT_LOCAL_URL",
            "AMRTRACE_COPILOT_HOSTED_MODEL"))
    assert "volume rm" not in (ROOT / "deploy/demo/reset.ps1").read_text(encoding="utf-8")


def test_migration_script_parses_as_posix_shell():
    config = yaml.safe_load((ROOT / "deploy/demo/compose.yml").read_text(encoding="utf-8"))
    svc = config["services"]["migrate"]
    assert svc["entrypoint"] == ["/bin/sh", "-ec"]
    script = svc["command"][0].replace("$$", "$")
    assert "Z28_SCHEMA_MISMATCH" in script and "Z28_REFUSED" in script
    assert "z28_demo_schema_stamp" in script
    p = subprocess.run(["sh", "-n", "-c", script], capture_output=True, text=True)
    assert p.returncode == 0, p.stderr


def test_launcher_guards_are_explicit():
    launcher = (ROOT / "deploy/demo/start.ps1").read_text(encoding="utf-8")
    reset = (ROOT / "deploy/demo/reset.ps1").read_text(encoding="utf-8")
    assert "amrtrace-z28-demo" in launcher and "amrtrace-z28-demo" in reset
    assert "-ConfirmDemoReset" in reset and "--volumes" in reset
    assert "-Offline" in launcher and "--pull', 'never" in launcher
    assert "start.ps1" in reset
    assert "docker compose down" not in launcher.lower()
