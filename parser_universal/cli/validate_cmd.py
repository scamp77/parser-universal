"""`parser-cli validate-config` — YAML structure check."""

from __future__ import annotations

import sys
from pathlib import Path


def cmd_validate_config(args) -> int:
    """Phase 2 stub: file exists + parseable YAML."""
    p = Path(args.path)
    if not p.exists():
        print(f"not found: {p}", file=sys.stderr)
        return 1
    try:
        import yaml
    except ImportError:
        print("pyyaml missing — pip install pyyaml. File exists only.", file=sys.stderr)
        return 0
    try:
        cfg = yaml.safe_load(p.read_text())
    except yaml.YAMLError as exc:
        print(f"YAML parse error: {exc}", file=sys.stderr)
        return 2
    if not isinstance(cfg, dict):
        print("top-level must be a mapping", file=sys.stderr)
        return 2
    required = {"adapter", "locator"}
    missing = required - cfg.keys()
    if missing:
        print(f"missing keys: {missing}", file=sys.stderr)
        return 2
    print(f"OK: {p}")
    return 0
