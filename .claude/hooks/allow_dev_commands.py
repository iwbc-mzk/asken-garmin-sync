#!/usr/bin/env python3
"""PreToolUse hook: auto-allow dev commands including multi-line python -c."""
import json
import sys

ALLOWED_PREFIXES = ("python ", "python3 ", "pytest ", "ruff ", "mypy ")

try:
    data = json.load(sys.stdin)
    command = data.get("tool_input", {}).get("command", "")

    first_real_line = ""
    for line in command.split("\n"):
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            first_real_line = stripped
            break

    if any(first_real_line.startswith(p) for p in ALLOWED_PREFIXES):
        print('{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "allow"}}')
except Exception:
    pass
