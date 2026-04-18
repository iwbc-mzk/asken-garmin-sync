#!/usr/bin/env python3
"""PreToolUse hook: auto-allow dev commands including multi-line python -c."""
import json
import sys

ALLOWED_PREFIXES = ("python ", "python3 ", "pytest ", "ruff ", "mypy ")

try:
    data = json.load(sys.stdin)
    command = data.get("tool_input", {}).get("command", "")
    first_line = command.split("\n")[0].strip()

    if any(first_line.startswith(p) for p in ALLOWED_PREFIXES):
        print('{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "allow"}}')
except Exception:
    pass
