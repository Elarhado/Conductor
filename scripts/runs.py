#!/usr/bin/env python3
"""Conductor runs & claims ledger — the mechanical backbone of circular verification.

What this script guarantees (mechanically):
  * one schema for evidence and claims; malformed records are rejected, never half-imported;
  * every verdict belongs to one exact version of a claim (content fingerprint incl. input
    files and the claims it depends on); any change sends the claim back to pending;
  * every prose unit of the delivered text is either tied to claims [Cn] or explicitly marked
    non-factual [~]; numbers must appear in the claims they cite;
  * a run can only be completed through `finalize`, which re-checks the final text and
    requires a verifier report for every verified claim it relies on.
What it cannot guarantee: that a source really supports a claim's meaning, or that a [~]
sentence carries no fact. Those are judged by the independent verifier agents.

Run layout: .conductor/runs/<run-id>/
  state.json      phase, round, gate, finalization record
  spec.md         forged prompt
  evidence/       raw records from scout/reader/analyst (same schema as claims)
  reports/        verifier reports, one file per verifier per round
  claims.jsonl    claims (current content + version)
  verdicts.jsonl  append-only verdict log, each bound to a claim fingerprint
  draft.md        text with [Cn] / [~] markers
  final.md        rendered result (written by finalize)

Record schema (evidence lines and claims):
  text*        the claim in one checkable sentence ("claim" accepted as alias)
  kind*        fact | number | date | quote | definition | calc | code | inference
  source       URL or file path (required except for inference)
  locator      where in the source (required for fact/number/date/quote/definition/calc)
  quote        exact supporting excerpt <= 400 chars (required for quote)
  defs         how the source defines the measured thing (required for number/calc;
               write "not stated" if the source gives none)
  units, published, source_type (primary|secondary), q (question id)
  inputs       list of files a calc depends on (required for calc; hashed into the version)
  depends_on   list of claim ids an inference rests on (required for inference)

Commands:
  new --slug S [--profile P] [--gate on|off]
  phase --run R --set PHASE          planning|producing|verifying|awaiting_user|delivering|aborted
                                     ("done" only via finalize)
  round --run R
  add --run R --text T --kind K [--source U] [--locator L] [--quote Q] [--defs D] [--units U]
      [--inputs a,b] [--depends C1,C2] [--published P] [--source-type T]
  import --run R --file F.jsonl      validates every line first; imports nothing on error
  validate --file F.jsonl            schema check only
  edit --run R --id C3 [field options as in add]   new version -> status pending
  verdict --run R --id C3 --status verified|refuted|unverifiable --by AGENT [--report PATH] [--note N]
  retract --run R --id C3 [--note N]
  list --run R [--status S] [--ids C1,C2]
  summary --run R
  check --run R --file DRAFT         exit 1 on blockers
  finalize --run R --file DRAFT [--out FINAL] [--lang ru|en]
  active
  hook-stop                          Stop-hook gate
"""
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import load_config, project_dir, read_hook_input, read_json, state_dir, write_json  # noqa: E402

KINDS = ("fact", "number", "date", "quote", "definition", "calc", "code", "inference")
VERDICTS = ("verified", "refuted", "unverifiable")
OPEN = ("pending", "refuted")
PHASES = ("planning", "producing", "verifying", "awaiting_user", "delivering", "done", "aborted")
CONTENT_FIELDS = ("text", "kind", "source", "locator", "quote", "defs", "units", "inputs", "depends_on")
OPTIONAL_FIELDS = ("published", "source_type", "q", "note")
ALLOWED_FIELDS = set(CONTENT_FIELDS) | set(OPTIONAL_FIELDS) | {"claim", "id"}
NEEDS_LOCATOR = ("fact", "number", "date", "quote", "definition", "calc")
NOT_FOUND = re.compile(r"^\s*not\s+found\b", re.I)

MARK = re.compile(r"\[(C\d+(?:\s*,\s*C\d+)*)\]")
NONFACT = re.compile(r"\[~\]")
SPACES = "    "
NUM = re.compile(r"(?<![\w.,])(\d{1,3}(?:[    ]\d{3})+|\d+)(?:([.,])(\d+))?(?![\w])")
LIST_PREFIX = re.compile(r"^\s*(?:[-*+•]|\d+[.)])\s+")


# ------------------------------------------------------------------ paths & io
def runs_dir(root):
    return state_dir(root) / "runs"


def run_path(root, run):
    p = runs_dir(root) / run
    if not p.is_dir():
        sys.exit("run not found: " + str(run))
    return p


def load_jsonl(path):
    out = []
    if Path(path).exists():
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            if line.strip():
                out.append(json.loads(line))
    return out


def save_jsonl(path, rows):
    tmp = Path(str(path) + ".tmp")
    tmp.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    os.replace(tmp, path)


def append_jsonl(path, row):
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def arg(argv, name, default=None):
    if name in argv:
        i = argv.index(name)
        if i + 1 < len(argv):
            return argv[i + 1]
    return default


def as_list(v):
    if v is None or v == "":
        return []
    if isinstance(v, list):
        return [str(x).strip() for x in v if str(x).strip()]
    return [x.strip() for x in str(v).split(",") if x.strip()]


# ------------------------------------------------------------------ schema
def normalise(rec):
    rec = dict(rec)
    if "claim" in rec and "text" not in rec:
        rec["text"] = rec.pop("claim")
    rec.pop("claim", None)
    for k in ("inputs", "depends_on"):
        rec[k] = as_list(rec.get(k))
    for k in CONTENT_FIELDS + OPTIONAL_FIELDS:
        if k not in ("inputs", "depends_on"):
            rec[k] = "" if rec.get(k) is None else str(rec.get(k)).strip()
    if rec.get("quote"):
        rec["quote"] = rec["quote"][:400]
    return rec


def validate(rec, root, known_ids):
    """Return a list of error strings for one record (already normalised)."""
    errs = []
    k = rec.get("kind")
    if not rec.get("text"):
        errs.append("text is empty (field 'text' or 'claim' required)")
    if k not in KINDS:
        errs.append("kind must be one of " + "|".join(KINDS))
        return errs
    if k != "inference" and not rec.get("source"):
        errs.append("source required for kind " + k)
    if k in NEEDS_LOCATOR and not rec.get("locator"):
        errs.append("locator required for kind " + k)
    if k == "quote" and not rec.get("quote"):
        errs.append("quote required for kind quote")
    if k in ("number", "calc") and not rec.get("defs"):
        errs.append("defs required for kind {} (use 'not stated' if the source gives none)".format(k))
    if k in ("number", "date") and not re.search(r"\d", rec.get("text", "")):
        errs.append("kind {} but text contains no digits".format(k))
    if k == "calc":
        if not rec["inputs"]:
            errs.append("inputs required for kind calc")
        for f in rec["inputs"] + ([rec["source"]] if rec.get("source") else []):
            if "://" not in f and not (Path(root) / f).exists() and not Path(f).exists():
                errs.append("file not found: " + f)
    if k == "inference" and not rec["depends_on"]:
        errs.append("depends_on required for kind inference")
    for d in rec["depends_on"]:
        if d not in known_ids:
            errs.append("depends_on refers to unknown claim " + d)
    return errs


def unknown_fields(raw):
    return sorted(set(raw) - ALLOWED_FIELDS)


# ------------------------------------------------------------------ versioning
def file_hash(root, f):
    p = Path(f) if Path(f).is_absolute() else Path(root) / f
    try:
        return hashlib.sha1(p.read_bytes()).hexdigest()[:12]
    except OSError:
        return "MISSING"


class Ledger:
    def __init__(self, root, rp):
        self.root, self.rp = root, rp
        self.claims = load_jsonl(rp / "claims.jsonl")
        self.by_id = {c["id"]: c for c in self.claims}
        self.verdicts = load_jsonl(rp / "verdicts.jsonl")
        self._fp = {}

    def save(self):
        save_jsonl(self.rp / "claims.jsonl", self.claims)

    def next_id(self):
        n = 0
        for c in self.claims:
            try:
                n = max(n, int(c["id"][1:]))
            except (KeyError, ValueError):
                pass
        return "C{}".format(n + 1)

    def fp(self, cid, _stack=()):
        if cid in self._fp:
            return self._fp[cid]
        c = self.by_id.get(cid)
        if c is None:
            return "MISSING"
        if cid in _stack:
            return "CYCLE"
        payload = {k: c.get(k) for k in CONTENT_FIELDS}
        payload["input_hashes"] = [file_hash(self.root, f) for f in c.get("inputs", [])]
        if c.get("kind") == "calc" and c.get("source") and "://" not in c["source"]:
            payload["script_hash"] = file_hash(self.root, c["source"])
        payload["deps"] = [self.fp(d, _stack + (cid,)) for d in c.get("depends_on", [])]
        h = hashlib.sha1(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]
        self._fp[cid] = h
        return h

    def verdict_for(self, cid):
        fp = self.fp(cid)
        for v in reversed(self.verdicts):
            if v["id"] == cid and v["fp"] == fp:
                return v
        return None

    def status(self, cid):
        c = self.by_id.get(cid)
        if c is None:
            return "unknown"
        if c.get("retracted"):
            return "retracted"
        v = self.verdict_for(cid)
        if v is None:
            return "pending"
        if v["status"] == "verified":
            for d in c.get("depends_on", []):
                if self.status(d) != "verified":
                    return "pending"
        return v["status"]

    def stale(self, cid):
        """True if the claim had verdicts for an older version."""
        fp = self.fp(cid)
        return any(v["id"] == cid and v["fp"] != fp for v in self.verdicts) and self.verdict_for(cid) is None

    def summary(self):
        s = {k: 0 for k in ("pending", "verified", "refuted", "unverifiable", "retracted")}
        stale = 0
        for c in self.claims:
            s[self.status(c["id"])] += 1
            stale += self.stale(c["id"])
        s["stale_after_edit"] = stale
        return s

    def add(self, rec, rnd):
        rec = normalise(rec)
        c = {"id": self.next_id(), "v": 1, "round": rnd, "retracted": False}
        for k in CONTENT_FIELDS + OPTIONAL_FIELDS:
            c[k] = rec.get(k, [] if k in ("inputs", "depends_on") else "")
        self.claims.append(c)
        self.by_id[c["id"]] = c
        self._fp = {}
        return c


# ------------------------------------------------------------------ text checks
def numbers_in(s):
    """Return list of (raw, set_of_candidate_values) for standalone numbers in s."""
    out = []
    for m in NUM.finditer(s):
        whole, sep, frac = m.group(1), m.group(2), m.group(3)
        start, end = m.span()
        if start > 0 and s[start - 1].isalpha() or end < len(s) and s[end:end + 1].isalpha():
            continue
        w = whole
        for ch in SPACES:
            w = w.replace(ch, "")
        cands = set()
        if sep and frac:
            if sep == "," and len(frac) == 3 and not any(ch in whole for ch in SPACES):
                cands.add(float(w + frac))          # 6,300 as thousands
            cands.add(float(w + "." + frac))        # 28,5 / 28.5 as decimal
        else:
            cands.add(float(w))
        out.append((m.group(0), cands, len(frac) if (sep and frac) else 0))
    return out


def number_supported(cands, decimals, claim_vals):
    for v in cands:
        for cv in claim_vals:
            if abs(v - cv) < 1e-9 or round(cv, decimals) == v:
                return True
    return False


def units_of(text):
    """Split a markdown draft into checkable prose units with line numbers."""
    units, in_code, lines = [], False, text.splitlines()
    table_header = False
    for i, line in enumerate(lines, 1):
        st = line.strip()
        if st.startswith("```"):
            in_code = not in_code
            continue
        if in_code or not st or st.startswith("#") or st.startswith("<!--"):
            continue
        if re.match(r"^\|?\s*:?-{3,}", st):
            continue
        if st.startswith("|"):
            nxt = lines[i].strip() if i < len(lines) else ""
            if re.match(r"^\|?\s*:?-{3,}", nxt):
                continue  # table header row
            units.append((i, st))
            continue
        body = LIST_PREFIX.sub("", st)
        if body.startswith(">"):
            body = body.lstrip("> ")
        parts = re.split(r"(?<=[.!?…])\s+(?=[A-ZА-ЯЁ\[(«\"0-9])", body)
        for p in parts:
            if p.strip():
                units.append((i, p.strip()))
    return units


def check(ledger, text, cfg):
    strict_sentences = cfg["verify"].get("strict_sentences", True)
    strict_numbers = cfg["verify"].get("strict_numbers", True)
    blockers, warnings, used = [], [], set()
    for ln, u in units_of(text):
        ids = []
        for grp in MARK.findall(u):
            ids += re.split(r"\s*,\s*", grp)
        nonfact = bool(NONFACT.search(u))
        bare = NONFACT.sub("", MARK.sub("", u))
        nums = numbers_in(bare)
        short = u[:120]
        for cid in ids:
            used.add(cid)
            st = ledger.status(cid)
            if st == "unknown":
                blockers.append("line {}: [{}] does not exist".format(ln, cid))
            elif st in ("pending", "refuted", "retracted"):
                why = " (changed after its last verdict)" if ledger.stale(cid) else ""
                blockers.append("line {}: [{}] is {}{}".format(ln, cid, st, why))
        if not ids and not nonfact:
            if strict_sentences:
                blockers.append("line {}: untraced statement (add [Cn] or mark non-factual [~]): «{}»".format(ln, short))
            elif nums and strict_numbers:
                blockers.append("line {}: numbers without a claim: «{}»".format(ln, short))
            continue
        if nonfact and nums:
            (blockers if strict_numbers else warnings).append(
                "line {}: [~] unit contains numbers {} — facts need claims: «{}»".format(
                    ln, ", ".join(n[0] for n in nums), short))
        if ids and nums:
            vals = set()
            for cid in ids:
                c = ledger.by_id.get(cid)
                if c:
                    for _, cands, _d in numbers_in(c.get("text", "") + " " + c.get("quote", "")):
                        vals |= cands
            for raw, cands, dec in nums:
                if not number_supported(cands, dec, vals):
                    (blockers if strict_numbers else warnings).append(
                        "line {}: number {} not found in cited claim(s) {}: «{}»".format(
                            ln, raw.strip(), ",".join(ids), short))
    return blockers, warnings, sorted(used)


def render(ledger, text, lang):
    order, num = [], {}
    unconf = "не подтверждено" if lang == "ru" else "unconfirmed"

    def repl(m):
        refs = []
        for cid in re.split(r"\s*,\s*", m.group(1)):
            c = ledger.by_id.get(cid)
            st = ledger.status(cid)
            if not c:
                continue
            if st == "unverifiable":
                refs.append("⚠ " + unconf)
                continue
            if st != "verified":
                continue
            if c.get("kind") == "inference":
                continue  # inference is shown through the sources of its premises
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

    body = NONFACT.sub("", MARK.sub(repl, text))
    body = re.sub(r"[ \t]+([.,;:!?])", r"\1", body)
    body = re.sub(r"[ \t]{2,}", " ", body)
    if order:
        title = "Источники" if lang == "ru" else "Sources"
        body = body.rstrip() + "\n\n## {}\n".format(title) + "\n".join(
            "{}. {}{}".format(i + 1, s or "(no source)", " — " + l if l else "")
            for i, (s, l) in enumerate(order)) + "\n"
    return body


# ------------------------------------------------------------------ gate
def gate(root):
    data = read_hook_input()
    if data.get("stop_hook_active") or not runs_dir(root).exists():
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
        if st.get("gate_blocks", 0) >= cfg["verify"]["max_gate_blocks"]:
            continue
        s = Ledger(root, rp).summary()
        msg = None
        if s["pending"] + s["refuted"]:
            msg = "{}: {} pending, {} refuted".format(rp.name, s["pending"], s["refuted"])
        elif st.get("phase") == "delivering":
            msg = "{}: delivering but not finalized".format(rp.name)
        if msg:
            st["gate_blocks"] = st.get("gate_blocks", 0) + 1
            write_json(rp / "state.json", st)
            problems.append(msg)
    if problems:
        print(json.dumps({"decision": "block", "reason": (
            "Conductor verification gate: " + "; ".join(problems) +
            ". Continue the verify loop, or run `runs.py finalize`, or set the phase to "
            "awaiting_user/aborted before finishing.")}))


# ------------------------------------------------------------------ commands
def record_from_args(a):
    rec = {}
    for k, opt in (("text", "--text"), ("kind", "--kind"), ("source", "--source"), ("locator", "--locator"),
                   ("quote", "--quote"), ("defs", "--defs"), ("units", "--units"), ("inputs", "--inputs"),
                   ("depends_on", "--depends"), ("published", "--published"), ("source_type", "--source-type"),
                   ("note", "--note"), ("q", "--q")):
        v = arg(a, opt)
        if v is not None:
            rec[k] = v
    return rec


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
    cfg = load_config(root)

    if cmd == "new":
        slug = re.sub(r"[^a-z0-9-]+", "-", (arg(a, "--slug") or "task").lower()).strip("-")[:40] or "task"
        rid = time.strftime("%Y%m%d-%H%M%S") + "-" + slug
        rp = runs_dir(root) / rid
        for d in ("evidence", "reports", "analysis"):
            (rp / d).mkdir(parents=True, exist_ok=True)
        write_json(rp / "state.json", {"id": rid, "phase": "planning", "round": 0,
                                       "profile": arg(a, "--profile", "auto"),
                                       "gate": arg(a, "--gate", "on") != "off", "created": int(time.time())})
        (rp / "claims.jsonl").touch()
        (rp / "verdicts.jsonl").touch()
        print(rid)
        return 0

    if cmd == "validate":
        errs, n = [], 0
        for i, line in enumerate(Path(arg(a, "--file")).read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            n += 1
            try:
                raw = json.loads(line)
            except ValueError as e:
                errs.append("line {}: invalid JSON ({})".format(i, e))
                continue
            rec = normalise(raw)
            if NOT_FOUND.match(rec.get("text", "")):
                continue
            uf = unknown_fields(raw)
            if uf:
                errs.append("line {}: unknown field(s) {}".format(i, ", ".join(uf)))
            ids = set(as_list(raw.get("depends_on")))  # standalone: deps checked on import
            errs += ["line {}: {}".format(i, e) for e in validate(rec, root, ids)]
        print("\n".join(errs) or "ok: {} record(s)".format(n))
        return 1 if errs else 0

    if cmd == "active":
        if runs_dir(root).exists():
            for rp in sorted(runs_dir(root).iterdir()):
                st = read_json(rp / "state.json", {}) or {}
                if st.get("phase") not in ("done", "aborted"):
                    s = Ledger(root, rp).summary()
                    print("{}\t{}\tround {}\t{}".format(rp.name, st.get("phase"), st.get("round", 0),
                                                        " ".join("{}={}".format(k, v) for k, v in s.items() if v)))
        return 0

    run = arg(a, "--run")
    if not run:
        sys.exit("--run required")
    rp = run_path(root, run)
    st = read_json(rp / "state.json", {}) or {}
    L = Ledger(root, rp)
    rnd = st.get("round", 0)

    if cmd == "phase":
        ph = arg(a, "--set")
        if ph == "done":
            sys.exit("refused: a run is completed only by `finalize` (checks the final text and verifier reports)")
        if ph not in PHASES:
            sys.exit("phase must be one of " + ", ".join(p for p in PHASES if p != "done"))
        st["phase"] = ph
        if ph in ("producing", "verifying"):
            st["gate_blocks"] = 0
        write_json(rp / "state.json", st)
        print(ph)

    elif cmd == "round":
        st["round"] = rnd + 1
        write_json(rp / "state.json", st)
        print(st["round"])
        if st["round"] > cfg["verify"]["max_rounds"]:
            print("ROUND LIMIT EXCEEDED: stop looping; retract or mark open claims unverifiable, or ask the user.")

    elif cmd == "add":
        raw = record_from_args(a)
        rec = normalise(raw)
        errs = validate(rec, root, set(L.by_id))
        if errs:
            print("\n".join("INVALID " + e for e in errs))
            return 1
        print(L.add(rec, rnd)["id"])
        L.save()

    elif cmd == "import":
        lines = Path(arg(a, "--file")).read_text(encoding="utf-8").splitlines()
        errs, recs, skipped = [], [], 0
        known = set(L.by_id)
        for i, line in enumerate(lines, 1):
            if not line.strip():
                continue
            try:
                raw = json.loads(line)
            except ValueError as e:
                errs.append("line {}: invalid JSON ({})".format(i, e))
                continue
            rec = normalise(raw)
            if NOT_FOUND.match(rec.get("text", "")):
                skipped += 1
                continue
            uf = unknown_fields(raw)
            if uf:
                errs.append("line {}: unknown field(s) {}".format(i, ", ".join(uf)))
            errs += ["line {}: {}".format(i, e) for e in validate(rec, root, known)]
            recs.append(rec)
        if errs:
            print("\n".join("INVALID " + e for e in errs))
            print("nothing imported (fix the records and retry)")
            return 1
        ids = [L.add(r, rnd)["id"] for r in recs]
        L.save()
        print(" ".join(ids) + ("  (skipped {} NOT FOUND record(s))".format(skipped) if skipped else ""))

    elif cmd == "edit":
        cid = arg(a, "--id")
        c = L.by_id.get(cid) or sys.exit("no such claim: " + str(cid))
        upd = normalise(dict({k: c.get(k) for k in CONTENT_FIELDS + OPTIONAL_FIELDS}, **record_from_args(a)))
        errs = validate(upd, root, set(L.by_id) - {cid})
        if errs:
            print("\n".join("INVALID " + e for e in errs))
            return 1
        before = L.fp(cid)
        for k in CONTENT_FIELDS + OPTIONAL_FIELDS:
            c[k] = upd[k]
        L._fp = {}
        if L.fp(cid) != before:
            c["v"] = c.get("v", 1) + 1
            c["round"] = rnd
        L.save()
        print("{} v{} -> {}".format(cid, c["v"], L.status(cid)))

    elif cmd in ("verdict", "set"):
        cid, status, by = arg(a, "--id"), arg(a, "--status"), arg(a, "--by")
        if cid not in L.by_id:
            sys.exit("no such claim: " + str(cid))
        if status not in VERDICTS:
            sys.exit("status must be one of " + "|".join(VERDICTS) + " (use retract/edit for other changes)")
        if not by:
            sys.exit("--by required (who issued the verdict)")
        report = arg(a, "--report", "")
        if status == "verified":
            allowed = cfg["verify"].get("verifiers", ["fact-checker", "code-verifier", "user"])
            if by.split(":")[-1] not in allowed:
                sys.exit("refused: 'verified' may only be issued by " + ", ".join(allowed))
            if by.split(":")[-1] != "user":
                rpath = Path(report) if Path(report).is_absolute() else Path(root) / report
                if not report or not rpath.exists():
                    sys.exit("refused: 'verified' needs --report pointing to the verifier's report file")
        append_jsonl(rp / "verdicts.jsonl", {"id": cid, "v": L.by_id[cid].get("v", 1), "fp": L.fp(cid),
                                             "status": status, "by": by, "report": report,
                                             "note": arg(a, "--note", ""), "round": rnd, "ts": int(time.time())})
        print(cid, status)

    elif cmd == "retract":
        cid = arg(a, "--id")
        c = L.by_id.get(cid) or sys.exit("no such claim: " + str(cid))
        c["retracted"] = True
        c["note"] = arg(a, "--note", c.get("note", ""))
        L.save()
        print(cid, "retracted")

    elif cmd == "list":
        want = arg(a, "--status")
        ids = set(as_list(arg(a, "--ids")))
        for c in L.claims:
            s = L.status(c["id"])
            if (want and s != want) or (ids and c["id"] not in ids):
                continue
            extra = []
            if c.get("defs"):
                extra.append("defs: " + c["defs"])
            if c.get("depends_on"):
                extra.append("depends: " + ",".join(c["depends_on"]))
            if c.get("inputs"):
                extra.append("inputs: " + ",".join(c["inputs"]))
            if L.stale(c["id"]):
                extra.append("CHANGED since last verdict")
            print("{}\tv{}\t{}\t{}\t{}\t{} {}\t{}".format(c["id"], c.get("v", 1), s, c["kind"], c["text"],
                                                       c.get("source", ""), c.get("locator", ""), " | ".join(extra)))

    elif cmd == "summary":
        print(json.dumps({"run": run, "phase": st.get("phase"), "round": rnd, **L.summary()}))

    elif cmd == "check":
        text = Path(arg(a, "--file")).read_text(encoding="utf-8")
        blockers, warnings, used = check(L, text, cfg)
        for b in blockers:
            print("BLOCKER " + b)
        for w in warnings[:40]:
            print("WARN " + w)
        print("refs used: {} | blockers: {} | warnings: {}".format(len(used), len(blockers), len(warnings)))
        return 1 if blockers else 0

    elif cmd == "finalize":
        draft = Path(arg(a, "--file"))
        text = draft.read_text(encoding="utf-8")
        blockers, _, used = check(L, text, cfg)
        for cid in used:
            if L.status(cid) == "verified":
                v = L.verdict_for(cid)
                if v and v["by"].split(":")[-1] != "user":
                    rpath = Path(v["report"]) if Path(v["report"]).is_absolute() else Path(root) / v["report"]
                    if not v["report"] or not rpath.exists():
                        blockers.append("[{}] verdict has no verifier report on disk".format(cid))
        if blockers:
            print("\n".join("BLOCKER " + b for b in blockers))
            print("not finalized")
            return 1
        lang = arg(a, "--lang", cfg.get("language_user", "ru"))
        out = Path(arg(a, "--out", str(rp / "final.md")))
        final = render(L, text, lang)
        out.write_text(final, encoding="utf-8")
        st.update({"phase": "done", "finalized": int(time.time()),
                   "final": str(out), "final_sha": hashlib.sha1(final.encode()).hexdigest()[:16],
                   "draft_sha": hashlib.sha1(text.encode()).hexdigest()[:16],
                   "claims_fp": {cid: L.fp(cid) for cid in used}})
        write_json(rp / "state.json", st)
        s = L.summary()
        print("finalized -> {} | claims used: {} | verified: {} | unverifiable shown as such: {}".format(
            out, len(used), sum(1 for c in used if L.status(c) == "verified"),
            sum(1 for c in used if L.status(c) == "unverifiable")))
        if s["pending"] or s["refuted"]:
            print("note: {} unused claim(s) remain open in the ledger".format(s["pending"] + s["refuted"]))
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
