from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).parents[2]
RUNNER_PATH = ROOT / ".spi" / "run_acceptance.py"
SPEC = importlib.util.spec_from_file_location("spi_run_acceptance", RUNNER_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("Unable to load SPI acceptance runner")
runner = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = runner
SPEC.loader.exec_module(runner)


def test_pytest_command_targets_only_the_live_acceptance_suite(tmp_path):
    command = runner._pytest_command(tmp_path / "junit.xml")

    assert str(ROOT / "tests" / "acceptance") in command
    assert "-p" in command
    assert "no:randomly" in command
    assert f"--junitxml={tmp_path / 'junit.xml'}" in command
