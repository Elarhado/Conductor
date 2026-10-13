"""Shared helpers for Conductor scripts. Python 3.8+, stdlib only."""
import json
import os
import sys
from pathlib import Path

STATE_DIR = ".conductor"

DEFAULT_CONFIG = {
    "profile": "auto",            # research | build | analytics | auto
    "language_user": "ru",        # language for user-facing answers and deliverables
    "language_internal": "en",    # language for specs, delegation prompts, cards, claims
    "verify": {
        "max_rounds": 4,          # producer -> verifier loop cap
        "gate": True,             # Stop hook refuses to finish a run with unresolved claims
        "max_gate_blocks": 3,
        "strict_numbers": True    # a number/date in the final text without [Cn] blocks delivery
    },
    "parallel": {"max_agents": 3},
    "forge": {"confirm": True, "skip_trivial": True},
    "codemap": {
        "max_files": 20000,
        "max_file_bytes": 1000000,
        "session_map_chars": 4000,
        "modules": {},            # {"module-id": ["glob", ...]} overrides auto grouping
        "ignore": []
    },
    # Relative weights used only to ESTIMATE limit consumption (USD per 1M tokens, list prices).
    # Check current prices and edit if they change.
    "price_per_mtok": {
        "opus":   {"in": 4.0,  "out": 20.0},
        "fable":  {"in": 10.0, "out": 50.0},
        "sonnet": {"in": 3.0,  "out": 15.0},
        "haiku":  {"in": 1.0,  "out": 5.0}
    },
    "cache_read_factor": 0.1,
    "cache_write_factor": 1.25
}


def project_dir(hook_input=None):
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    if env:
        return Path(env)
    if hook_input and hook_input.get("cwd"):
        return Path(hook_input["cwd"])
    return Path.cwd()


def state_dir(root):
    return Path(root) / STATE_DIR


def deep_merge(base, over):
    out = dict(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config(root):
    p = state_dir(root) / "config.json"
    if p.exists():
        try:
            return deep_merge(DEFAULT_CONFIG, json.loads(p.read_text(encoding="utf-8")))
        except (ValueError, OSError):
            pass
    return json.loads(json.dumps(DEFAULT_CONFIG))


def read_hook_input():
    try:
        data = sys.stdin.read()
        return json.loads(data) if data.strip() else {}
    except ValueError:
        return {}


def emit_context(event, text):
    """Print hookSpecificOutput.additionalContext JSON (nothing if text is empty)."""
    if text:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": event,
                                                 "additionalContext": text}}))


def write_json(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default
