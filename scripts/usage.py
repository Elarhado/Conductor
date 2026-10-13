#!/usr/bin/env python3
"""Conductor usage ledger: where did the tokens go, per model and per agent.

Reads Claude Code transcripts (main session + subagent transcripts) and keeps one
snapshot per session in <project>/.conductor/usage/<session>.json.

Commands:
  hook-stop            Stop hook (stdin JSON): refresh the snapshot for this session
  hook-subagent-stop   SubagentStop hook: remember agent_id -> agent_type
  report [--days N]    print a markdown report (default: last 7 days)

Numbers are tokens taken from the transcript's usage fields. The "est. cost" column
is an ESTIMATE from list prices in config (price_per_mtok); plan limits are not
published per token, so use it to compare shares, not as an exact limit meter.
"""
import glob
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import load_config, project_dir, read_hook_input, read_json, state_dir, write_json  # noqa: E402

FIELDS = ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")


def family(model):
    m = (model or "").lower()
    for f in ("fable", "opus", "sonnet", "haiku"):
        if f in m:
            return f
    return "other"


def parse_transcript(path):
    """Return {message_id: (model, usage_dict)} using the last record per message id."""
    out = {}
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if '"usage"' not in line:
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                msg = rec.get("message") if isinstance(rec.get("message"), dict) else None
                if not msg or not isinstance(msg.get("usage"), dict):
                    continue
                mid = msg.get("id") or rec.get("requestId") or rec.get("uuid")
                if not mid:
                    continue
                u = msg["usage"]
                out[mid] = (msg.get("model") or "unknown",
                            {k: int(u.get(k) or 0) for k in FIELDS})
    except OSError:
        pass
    return out


def subagent_files(transcript_path, session_id):
    t = Path(transcript_path)
    cands = [t.parent / session_id / "subagents", t.with_suffix("") / "subagents"]
    files = []
    for c in cands:
        if c.is_dir():
            files += sorted(glob.glob(str(c / "*.jsonl")))
    return sorted(set(files))


def add(acc, usage):
    for k in FIELDS:
        acc[k] = acc.get(k, 0) + usage[k]
    acc["calls"] = acc.get("calls", 0) + 1


def snapshot(transcript_path, session_id, agent_types):
    by_model, by_agent = {}, {}
    main = parse_transcript(transcript_path)
    for mid, (model, u) in main.items():
        add(by_model.setdefault(model, {}), u)
        add(by_agent.setdefault("main", {"model": model}), u)
    for f in subagent_files(transcript_path, session_id):
        aid = Path(f).stem.replace("agent-", "")
        atype = agent_types.get(aid, "subagent")
        for mid, (model, u) in parse_transcript(f).items():
            add(by_model.setdefault(model, {}), u)
            key = "{} ({})".format(atype, family(model))
            add(by_agent.setdefault(key, {"model": model}), u)
    return {"session": session_id, "updated": int(time.time()),
            "by_model": by_model, "by_agent": by_agent}


def cost(cfg, model, u):
    p = cfg["price_per_mtok"].get(family(model))
    if not p:
        return 0.0
    inp = (u.get("input_tokens", 0) + cfg["cache_write_factor"] * u.get("cache_creation_input_tokens", 0)
           + cfg["cache_read_factor"] * u.get("cache_read_input_tokens", 0))
    return (inp * p["in"] + u.get("output_tokens", 0) * p["out"]) / 1e6


def hook_stop(root):
    data = read_hook_input()
    tp, sid = data.get("transcript_path"), data.get("session_id")
    if not tp or not sid or not state_dir(root).exists():
        return
    types = read_json(state_dir(root) / "usage" / "_agents.json", {}) or {}
    snap = snapshot(tp, sid, types)
    write_json(state_dir(root) / "usage" / (sid + ".json"), snap)


def hook_subagent_stop(root):
    data = read_hook_input()
    aid, atype = data.get("agent_id"), data.get("agent_type")
    if not aid or not atype or not state_dir(root).exists():
        return
    p = state_dir(root) / "usage" / "_agents.json"
    types = read_json(p, {}) or {}
    types[aid] = atype
    write_json(p, types)


def fmt(n):
    return "{:,}".format(int(n)).replace(",", " ")


def report(root, days):
    cfg = load_config(root)
    since = time.time() - days * 86400
    by_model, by_agent, sessions = {}, {}, 0
    for f in glob.glob(str(state_dir(root) / "usage" / "*.json")):
        if Path(f).name.startswith("_"):
            continue
        s = read_json(f, {})
        if not s or s.get("updated", 0) < since:
            continue
        sessions += 1
        for model, u in s.get("by_model", {}).items():
            acc = by_model.setdefault(model, {})
            for k, v in u.items():
                acc[k] = acc.get(k, 0) + v
        for ag, u in s.get("by_agent", {}).items():
            acc = by_agent.setdefault(ag, {"model": u.get("model")})
            for k, v in u.items():
                if k != "model":
                    acc[k] = acc.get(k, 0) + v
    if not sessions:
        return "No usage snapshots in the last {} day(s). They appear after the first turn in a project with .conductor/.".format(days)

    def table(title, rows, keyname):
        total = sum(cost(cfg, r[1].get("model", r[0]), r[1]) for r in rows) or 1e-9
        out = ["### " + title, "",
               "| {} | calls | input | output | cache write | cache read | est. $ | share |".format(keyname),
               "|---|---:|---:|---:|---:|---:|---:|---:|"]
        for name, u in sorted(rows, key=lambda r: -cost(cfg, r[1].get("model", r[0]), r[1])):
            c = cost(cfg, u.get("model", name), u)
            out.append("| {} | {} | {} | {} | {} | {} | {:.2f} | {:.0%} |".format(
                name, fmt(u.get("calls", 0)), fmt(u.get("input_tokens", 0)), fmt(u.get("output_tokens", 0)),
                fmt(u.get("cache_creation_input_tokens", 0)), fmt(u.get("cache_read_input_tokens", 0)),
                c, c / total))
        return "\n".join(out)

    md = ["## Conductor usage — last {} day(s), {} session(s)".format(days, sessions), "",
          table("By model", list(by_model.items()), "model"), "",
          table("By agent", list(by_agent.items()), "agent"), "",
          "Est. $ uses list prices from config; it shows relative weight, not your exact plan limit."]
    delegated = sum(cost(cfg, u.get("model", a), u) for a, u in by_agent.items() if a != "main")
    allc = sum(cost(cfg, u.get("model", a), u) for a, u in by_agent.items()) or 1e-9
    md.append("Delegated share of estimated cost: {:.0%}.".format(delegated / allc))
    return "\n".join(md)


def main(argv):
    root = project_dir()
    cmd = argv[0] if argv else "report"
    try:
        if cmd == "hook-stop":
            hook_stop(root)
        elif cmd == "hook-subagent-stop":
            hook_subagent_stop(root)
        elif cmd == "report":
            days = 7
            if "--days" in argv:
                days = float(argv[argv.index("--days") + 1])
            print(report(root, days))
        else:
            print(__doc__)
            return 2
    except Exception as e:
        if cmd.startswith("hook-"):
            sys.stderr.write("usage hook error: {}\n".format(e))
            return 0
        raise
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
