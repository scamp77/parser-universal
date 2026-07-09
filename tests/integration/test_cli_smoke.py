"""Smoke-test the parser-cli end-to-end against the bundled sample.gpx.

This is the Phase 1 DoD: `python -m parser_universal.cli run --adapter gpx ...
` exits 0 and prints a JSON record.
"""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SAMPLE = ROOT / "tests" / "data" / "sample.gpx"


def test_parser_cli_gpx_runs():
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "parser_universal.cli",
            "run",
            "--adapter",
            "gpx",
            "--locator",
            str(SAMPLE),
        ],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )
    assert proc.returncode == 0, f"stderr={proc.stderr}"
    payload = json.loads(proc.stdout)
    assert payload["source"] == "gpx"
    assert payload["coord_hint"] == [55.7558, 37.6173]


def test_parser_cli_validate_config_ok(tmp_path):
    cfg = tmp_path / "smoke.yaml"
    cfg.write_text("adapter: gpx\nlocator: tests/data/sample.gpx\n")
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "parser_universal.cli",
            "validate-config",
            str(cfg),
        ],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )
    assert proc.returncode == 0, f"stderr={proc.stderr}"


def test_parser_cli_validate_config_missing_file(tmp_path):
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "parser_universal.cli",
            "validate-config",
            str(tmp_path / "nope.yaml"),
        ],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )
    assert proc.returncode != 0
