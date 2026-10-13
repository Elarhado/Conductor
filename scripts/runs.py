#!/usr/bin/env python3
"""Conductor runs & claims ledger — the mechanical backbone of circular verification.

Every factual statement that reaches the user must trace to a claim in the run's
ledger with status "verified" (or be explicitly shown as unconfirmed). Models do
the judging; this script does the bookkeeping and the checks a model is bad at:
missing references, unverified claims slipping through, numbers without a source.

Run layout: .conductor/runs/<run-id>/
  state.json     phase, round, gate settings
  spec.md        forged prompt (written by the orchestrator)
  claims.jsonl   one claim per line
  evidence/      raw notes from scout/reader agents
  rounds.md      verification log (one section per round)

Claim fields: id, text, kind (fact|number|date|quote|definition|code|calc), source,
locator, quote, status (pending|verified|refuted|unverifiable|retracted), note, round.

Commands:
  new --slug S [--profile P] [--gate on|off]          create run, print id
  phase --run R --set PHASE                           planning|producing|verifying|
                                                      awaiting_user|delivering|done|aborted
  round --run R                                       increment round counter, print it
  add --run R --text T [--kind K] [--source U] [--locator L] [--quote Q]
  import --run R --file claims.jsonl                  bulk add (fields as above)
  set --run R --id C3 --status S [--note N] [--source U] [--locator L] [--text T]
  list --run R [--status S] [--ids C1,C2]
  summary --run R
  check --run R --file DRAFT                          traceability check (exit 1 on blockers)
  render --run R --file DRAFT --out FINAL [--lang ru|en]
  active                                              list runs not done/aborted
  hook-stop                                           Stop-hook verification gate
"""
import json
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import load_config, project_dir, read_hook_input, read_json, state_dir, write_json  # noqa: E402

STATUSES = ("pending", "verified", "refuted", "unverifiable", "retracted")
OPEN = ("pending", "refuted")
PHASES = ("planning", "producing", "verifying", "awaiting_user", "delivering", "done", "aborted")
MARK = re.compile(r"\[(C\d+(?:\s*,\s*C\d+)*)\]")
NUMERIC = re.compile(r"(?<![\w\[])(?:\d[\d\s.,]*\d|\d)(?:\s?(?:%|‰|млн|млрд|тыс|k|M|B|GHz|МГц|ГГц|MHz|km|км|м|ms|мс))?(?![\w\]])")
NUMERIC_EXEMPT = re.compile(r"^\d{1,2}$")  # list ordinals and small counts are not flagged


def runs_dir(root):
    return state_dir(root) / "runs"


def run_path(root, run):
    p = runs_dir(root) / run
    if not p.is_dir():
        sys.exit("run not found: " + run)
    return p


def load_claims(rp):
    out = []
    f = rp / "claims.jsonl"
    if f.exists():
        for line in f.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    out.append(json.loads(line))
                except ValueError:
                    pass
    return out


def save_claims(rp, claims):
    tmp = rp / "claims.jsonl.tmp"
    tmp.write_text("".join(json.dumps(c, ensure_ascii=False) + "\n" for c in claims), encoding="utf-8")
    os.replace(tmp, rp / "claims.jsonl")


def next_id(claims):
    n = 0
    for c in claims:
        try:
            n = max(n, int(c["id"][1:]))
        except (KeyError, ValueError):
            pass
    return "C{}".format(n + 1)


def arg(argv, name, default=None):
    if name in argv:
        i = argv.index(name)
        if i + 1 < len(argv):
            return argv[i + 1]
    return default


def new_claim(claims, text, kind="fact", source="", locator="", quote="", rnd=0):
    c = {"id": next_id(claims), "text": text, "kind": kind or "fact", "source": source or "",
         "locator": locator or "", "quote": (quote or "")[:400], "status": "pending", "note": "",
         "round": rnd}
    claims.append(c)
    return c


def summary(claims):
    s = {k: 0 for k in STATUSES}
    for c in claims:
        s[c.get("status", "pending")] = s.get(c.get("status", "pending"), 0) + 1
    return s


def split_sentences(text):
    # Keep it simple and language-agnostic.
    parts = re.split(r"(?<=[.!?…])\s+|\n{2,}|\n(?=[-*•|#])", text)
    return [p.strip() for p in parts if p.strip()]


def check(rp, text, strict=True):
    claims = {c["id"]: c for c in load_claims(rp)}
    blockers, warnings = [], []
    used = set()
    in_code = False
    for lineno, line in enumerate(text.splitlines(), 1):
        if line.strip().startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            continue
        for grp in MARK.findall(line):
            for cid in re.split(r"\s*,\s*", grp):
                used.add(cid)
                c = claims.get(cid)
                if c is None:
                    blockers.append("line {}: [{}] does not exist in the ledger".format(lineno, cid))
                elif c["status"] in OPEN:
                    blockers.append("line {}: [{}] is {} — resolve before delivery".format(lineno, cid, c["status"]))
                elif c["status"] == "retracted":
                    blockers.append("line {}: [{}] was retracted — remove the statement".format(lineno, cid))
    for sent in split_sentences(text):
        if sent.startswith(("#", "```", "|---")) or MARK.search(sent):
            continue
        nums = [n.strip() for n in NUMERIC.findall(sent)]
        nums = [n for n in nums if not NUMERIC_EXEMPT.match(n.replace(" ", ""))]
        if nums:
            (blockers if strict else warnings).append(
                "numbers without a claim reference: «{}»".format(sent[:140]))
    open_unused = [cid for cid, c in claims.items() if c["status"] in OPEN and cid not in used]
    return blockers, warnings, sorted(used), open_unused


def render(rp, text, lang):
    claims = {c["id"]: c for c in load_claims(rp)}
    order, num = [], {}
    unconf = "не подтверждено" if lang == "ru" else "unconfirmed"

    def repl(m):
        refs = []
        for cid in re.split(r"\s*,\s*", m.group(1)):
            c = claims.get(cid)
            if not c:
                continue
            if c["status"] == "unverifiable":
                refs.append("⚠ " + unconf)
                continue
            if c["status"] != "verified":
                continue
            key = (c.get("source") or "", c.get("locator") or "")
            if key not in num:
                num[key] = len(num) + 1
                order.append(key)
            refs.append(str(num[key]))
        uniq = []
        for r in refs:
            if r not in uniq:
                uniq.append(r)
        return "[" + ", ".join(uniq) + "]" if uniq else ""

    body = MARK.sub(repl, text)
    if order:
        title = "Источники" if lang == "ru" else "Sources"
        body = body.rstrip() + "\n\n## {}\n".format(title) + "\n".join(
            "{}. {}{}".format(i + 1, s or "(no source)", " — " + l if l else "") for i, (s, l) in enumerate(order)) + "\n"
    return body


def gate(root):
    data = read_hook_input()
    if data.get("stop_hook_active"):
        return
    if not runs_dir(root).exists():
        return
    cfg = load_config(root)
    if not cfg["verify"].get("gate", True):
        return
    problems = []
    for rp in sorted(runs_dir(root).iterdir()):
        st = read_json(rp / "state.json", None)
        if not st or not st.get("gate", True):
            continue
        if st.get("phase") in ("done", "aborted", "awaiting_user", "planning"):
            continue
        s = summary(load_claims(rp))
        open_n = s["pending"] + s["refuted"]
        if open_n == 0:
            continue
        if st.get("gate_blocks", 0) >= cfg["verify"]["max_gate_blocks"]:
            continue
        st["gate_blocks"] = st.get("gate_blocks", 0) + 1
        write_json(rp / "state.json", st)
        problems.append("{}: {} pending, {} refuted (round {}/{})".format(
            rp.name, s["pending"], s["refuted"], st.get("round", 0), cfg["verify"]["max_rounds"]))
    if problems:
        reason = ("Conductor verification gate: run(s) still have unresolved claims — " + "; ".join(problems) +
                  ". Continue the verify loop (conductor:verify), or mark claims unverifiable/retracted and set "
                  "the run phase to awaiting_user/done before finishing.")
        print(json.dumps({"decision": "block", "reason": reason}))


def main(argv):
    if not argv:
        print(__doc__)
        return 0
    cmd, a = argv[0], argv[1:]
    root = project_dir()
    if cmd == "hook-stop":
        try:
            gate(root)
        except Exception as e:
            sys.stderr.write("gate error: {}\n".format(e))
        return 0
    if cmd == "new":
        slug = re.sub(r"[^a-z0-9-]+", "-", (arg(a, "--slug") or "task").lower()).strip("-")[:40] or "task"
        rid = time.strftime("%Y%m%d-%H%M%S") + "-" + slug
        rp = runs_dir(root) / rid
        (rp / "evidence").mkdir(parents=True, exist_ok=True)
        write_json(rp / "state.json", {"id": rid, "phase": "planning", "round": 0,
                                       "profile": arg(a, "--profile", "auto"),
                                       "gate": arg(a, "--gate", "on") != "off",
                                       "created": int(time.time())})
        (rp / "claims.jsonl").touch()
        print(rid)
        return 0
    if cmd == "active":
        if runs_dir(root).exists():
            for rp in sorted(runs_dir(root).iterdir()):
                st = read_json(rp / "state.json", {}) or {}
                if st.get("phase") not in ("done", "aborted"):
                    s = summary(load_claims(rp))
                    print("{}\t{}\tround {}\t{}".format(rp.name, st.get("phase"), st.get("round", 0),
                                                        " ".join("{}={}".format(k, v) for k, v in s.items() if v)))
        return 0
    run = arg(a, "--run")
    if not run:
        sys.exit("--run required")
    rp = run_path(root, run)
    st = read_json(rp / "state.json", {}) or {}
    if cmd == "phase":
        ph = arg(a, "--set")
        if ph not in PHASES:
            sys.exit("phase must be one of " + ", ".join(PHASES))
        st["phase"] = ph
        if ph in ("producing", "verifying"):
            st["gate_blocks"] = 0
        write_json(rp / "state.json", st)
        print(ph)
    elif cmd == "round":
        st["round"] = st.get("round", 0) + 1
        write_json(rp / "state.json", st)
        cfg = load_config(root)
        print(st["round"])
        if st["round"] > cfg["verify"]["max_rounds"]:
            print("ROUND LIMIT EXCEEDED: stop looping; mark remaining claims unverifiable or ask the user.")
    elif cmd == "add":
        claims = load_claims(rp)
        c = new_claim(claims, arg(a, "--text", ""), arg(a, "--kind"), arg(a, "--source"),
                      arg(a, "--locator"), arg(a, "--quote"), st.get("round", 0))
        save_claims(rp, claims)
        print(c["id"])
    elif cmd == "import":
        claims = load_claims(rp)
        ids = []
        for line in Path(arg(a, "--file")).read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            d = json.loads(line)
            c = new_claim(claims, d.get("text", ""), d.get("kind"), d.get("source"), d.get("locator"),
                          d.get("quote"), st.get("round", 0))
            ids.append(c["id"])
        save_claims(rp, claims)
        print(" ".join(ids))
    elif cmd == "set":
        claims = load_claims(rp)
        cid, status = arg(a, "--id"), arg(a, "--status")
        if status and status not in STATUSES:
            sys.exit("status must be one of " + ", ".join(STATUSES))
        hit = False
        for c in claims:
            if c["id"] == cid:
                hit = True
                if status:
                    c["status"] = status
                for k in ("note", "source", "locator", "text", "quote"):
                    v = arg(a, "--" + k)
                    if v is not None:
                        c[k] = v
                c["round"] = st.get("round", 0)
        if not hit:
            sys.exit("no such claim: " + str(cid))
        save_claims(rp, claims)
        print(cid, status or "")
    elif cmd == "list":
        want = arg(a, "--status")
        ids = set((arg(a, "--ids") or "").split(",")) - {""}
        for c in load_claims(rp):
            if want and c["status"] != want:
                continue
            if ids and c["id"] not in ids:
                continue
            print("{id}\t{status}\t{kind}\t{text}\t{source} {locator}".format(**c))
    elif cmd == "summary":
        s = summary(load_claims(rp))
        print(json.dumps({"run": run, "phase": st.get("phase"), "round": st.get("round", 0), **s}))
    elif cmd == "check":
        text = Path(arg(a, "--file")).read_text(encoding="utf-8")
        strict = load_config(root)["verify"].get("strict_numbers", True)
        blockers, warnings, used, open_unused = check(rp, text, strict)
        for b in blockers:
            print("BLOCKER " + b)
        for w in warnings[:40]:
            print("WARN " + w)
        if open_unused:
            print("INFO open claims not used in draft: " + ", ".join(open_unused))
        print("refs used: {} | blockers: {} | warnings: {}".format(len(used), len(blockers), len(warnings)))
        return 1 if blockers else 0
    elif cmd == "render":
        text = Path(arg(a, "--file")).read_text(encoding="utf-8")
        blockers, _, _, _ = check(rp, text, load_config(root)["verify"].get("strict_numbers", True))
        if blockers:
            print("\n".join("BLOCKER " + b for b in blockers))
            return 1
        out = render(rp, text, arg(a, "--lang", "ru"))
        Path(arg(a, "--out")).write_text(out, encoding="utf-8")
        print("rendered -> " + arg(a, "--out"))
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
