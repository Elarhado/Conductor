"""Run: python -m unittest discover -s tests -v   (from the repo root)"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
S = ROOT / "scripts"


def run(script, args, cwd, stdin=""):
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(cwd))
    p = subprocess.run([sys.executable, str(S / script)] + args, cwd=cwd, input=stdin,
                       capture_output=True, text=True, env=env)
    return p.returncode, p.stdout, p.stderr


def write(base, rel, text):
    p = Path(base) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


class CodemapTest(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        write(self.d, "src/game/engine.ts", "import { draw } from '../ui/render'\nimport u from './util'\n")
        write(self.d, "src/game/util.ts", "export default 1\n")
        write(self.d, "src/ui/render.ts", "export function draw(){}\n")
        write(self.d, "src/ui/menu.ts", "import {run} from '../game/engine'\n")
        write(self.d, "main.py", "from pkg import helper\n")
        write(self.d, "pkg/__init__.py", "")
        write(self.d, "pkg/helper.py", "x = 1\n")
        write(self.d, "Assets/Scripts/Net/Lobby.cs", "// @map: depends=Assets/Scripts/Core/Events.cs\n")
        write(self.d, "Assets/Scripts/Core/Events.cs", "class E {}\n")
        write(self.d, "node_modules/x/a.js", "junk")
        rc, out, err = run("codemap.py", ["init"], self.d)
        self.assertEqual(rc, 0, err)
        self.m = json.loads((self.d / ".conductor/map.json").read_text())

    def test_index_and_ignore(self):
        files = self.m["files"]
        self.assertNotIn("node_modules/x/a.js", files)
        self.assertEqual(files["src/game/engine.ts"]["d"], ["src/game/util.ts", "src/ui/render.ts"])
        self.assertEqual(files["main.py"]["d"], ["pkg/helper.py"])
        self.assertEqual(files["Assets/Scripts/Net/Lobby.cs"]["d"], ["Assets/Scripts/Core/Events.cs"])
        self.assertTrue((self.d / ".conductor/MAP.md").exists())
        self.assertTrue((self.d / ".conductor/cards/src__game.md").exists())

    def test_post_edit_reports_dependents(self):
        run("codemap.py", ["fresh", "src/ui", "src/game"], self.d)
        write(self.d, "src/ui/render.ts", "export function draw(){ return 2 }\n")
        payload = json.dumps({"tool_name": "Edit", "tool_input": {"file_path": str(self.d / "src/ui/render.ts")}})
        rc, out, err = run("codemap.py", ["hook-post-edit"], self.d, payload)
        self.assertEqual(rc, 0, err)
        ctx = json.loads(out)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("src/game/engine.ts", ctx)
        self.assertIn("src/ui", ctx)
        rc, out, _ = run("codemap.py", ["stale"], self.d)
        self.assertIn("src/ui", out)
        self.assertNotIn("src/game\t", out)

    def test_unchanged_edit_is_silent(self):
        payload = json.dumps({"tool_input": {"file_path": str(self.d / "src/game/util.ts")}})
        rc, out, _ = run("codemap.py", ["hook-post-edit"], self.d, payload)
        self.assertEqual(out.strip(), "")

    def test_sync_handles_delete(self):
        (self.d / "src/game/util.ts").unlink()
        rc, out, err = run("codemap.py", ["sync"], self.d)
        self.assertEqual(rc, 0, err)
        m = json.loads((self.d / ".conductor/map.json").read_text())
        self.assertNotIn("src/game/util.ts", m["files"])
        self.assertEqual(m["files"]["src/game/engine.ts"]["d"], ["src/ui/render.ts"])

    def test_session_start_injects_map(self):
        rc, out, _ = run("codemap.py", ["hook-session-start"], self.d, "{}")
        ctx = json.loads(out)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("conductor:conduct", ctx)
        self.assertIn("| module |", ctx)

    def test_import_of_future_file_links_on_creation(self):
        write(self.d, "src/game/boot.ts", "import { net } from './net'\n")
        payload = lambda f: json.dumps({"tool_input": {"file_path": str(self.d / f)}})
        run("codemap.py", ["hook-post-edit"], self.d, payload("src/game/boot.ts"))
        write(self.d, "src/game/net.ts", "export const net = 1\n")
        rc, out, err = run("codemap.py", ["hook-post-edit"], self.d, payload("src/game/net.ts"))
        self.assertIn("src/game/boot.ts", out)
        m = json.loads((self.d / ".conductor/map.json").read_text())
        self.assertEqual(m["files"]["src/game/boot.ts"]["d"], ["src/game/net.ts"])

    def test_sync_links_python_module_created_outside(self):
        write(self.d, "app.py", "import tools.report\n")
        run("codemap.py", ["sync"], self.d)
        write(self.d, "tools/report.py", "x = 1\n")
        run("codemap.py", ["sync"], self.d)
        m = json.loads((self.d / ".conductor/map.json").read_text())
        self.assertEqual(m["files"]["app.py"]["d"], ["tools/report.py"])

    def test_ensure_connects_new_project_then_syncs(self):
        fresh = Path(tempfile.mkdtemp())
        write(fresh, "src/a.py", "from src import b\n")
        write(fresh, "src/b.py", "x = 1\n")
        rc, out, err = run("codemap.py", ["ensure"], fresh)
        self.assertEqual(rc, 0, err)
        self.assertIn("initialised now", out)
        self.assertIn("| module |", out)
        self.assertTrue((fresh / ".conductor/.gitignore").exists())
        self.assertEqual(sorted(p.name for p in fresh.iterdir()), [".conductor", "src"])
        write(fresh, "src/c.py", "y = 2\n")
        rc, out, _ = run("codemap.py", ["ensure"], fresh)
        self.assertIn("map synced (3 files", out)

    def test_ensure_refuses_home(self):
        env = dict(os.environ, CLAUDE_PROJECT_DIR=str(Path.home()))
        p = subprocess.run([sys.executable, str(S / "codemap.py"), "ensure"], capture_output=True, text=True, env=env)
        self.assertEqual(p.returncode, 3)
        self.assertIn("refusing", p.stdout)

    def test_hooks_silent_without_project(self):
        empty = Path(tempfile.mkdtemp())
        for cmd in ("hook-session-start", "hook-post-edit"):
            rc, out, _ = run("codemap.py", [cmd], empty, "{}")
            self.assertEqual((rc, out.strip()), (0, ""))
        self.assertFalse((empty / ".conductor").exists())


class RunsTest(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        rc, out, err = run("runs.py", ["new", "--slug", "Test Run"], self.d)
        self.assertEqual(rc, 0, err)
        self.r = out.strip()
        self.rp = self.d / ".conductor/runs" / self.r
        self.report = self.rp / "reports/round-1-fact-checker.md"
        self.report.write_text("C1 | verified | ok\n")

    def R(self, *args, stdin=""):
        return run("runs.py", list(args), self.d, stdin)

    def add(self, text, **kw):
        a = ["add", "--run", self.r, "--text", text, "--kind", kw.get("kind", "number"),
             "--source", kw.get("source", "https://x/a"), "--locator", kw.get("locator", "p.3"),
             "--defs", kw.get("defs", "active SIM, 3 months")]
        for k in ("inputs", "depends", "quote"):
            if k in kw:
                a += ["--" + k, kw[k]]
        rc, out, err = self.R(*a)
        self.assertEqual(rc, 0, out + err)
        return out.strip()

    def verify(self, cid):
        rc, out, err = self.R("verdict", "--run", self.r, "--id", cid, "--status", "verified",
                              "--by", "conductor:fact-checker", "--report", str(self.report))
        self.assertEqual(rc, 0, out + err)

    def status(self, cid):
        return self.R("list", "--run", self.r, "--ids", cid)[1].split("\t")[2]

    # 1. one schema, atomic import
    def test_import_accepts_scout_format_and_keeps_definitions(self):
        ev = self.rp / "evidence/scout-a.jsonl"
        ev.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in [
            {"q": "Q1", "claim": "A had 81 mln subscribers at end of 2025", "kind": "number",
             "source": "https://x/a", "locator": "p.3", "quote": "81 mln", "defs": "SIM active 3 months",
             "published": "2026-02-01", "source_type": "primary"},
            {"q": "Q2", "claim": "NOT FOUND", "kind": "fact"}]) + "\n")
        rc, out, err = self.R("import", "--run", self.r, "--file", str(ev))
        self.assertEqual(rc, 0, out + err)
        self.assertIn("skipped 1", out)
        c = json.loads((self.rp / "claims.jsonl").read_text().splitlines()[0])
        self.assertEqual(c["text"], "A had 81 mln subscribers at end of 2025")
        self.assertEqual((c["defs"], c["published"]), ("SIM active 3 months", "2026-02-01"))

    def test_import_rejects_bad_records_atomically(self):
        ev = self.rp / "evidence/bad.jsonl"
        ev.write_text(json.dumps({"claim": "ok fact", "kind": "fact", "source": "u", "locator": "l"}) + "\n" +
                      json.dumps({"text": "", "kind": "number", "source": "u"}) + "\n" +
                      json.dumps({"text": "x", "kind": "fact", "source": "u", "locator": "l", "bogus": 1}) + "\n")
        rc, out, _ = self.R("import", "--run", self.r, "--file", str(ev))
        self.assertEqual(rc, 1)
        self.assertIn("text is empty", out)
        self.assertIn("defs required", out)
        self.assertIn("unknown field", out)
        self.assertEqual((self.rp / "claims.jsonl").read_text().strip(), "")

    # 2. versioned verdicts
    def test_edit_after_verification_resets_status(self):
        c1 = self.add("A has 81 mln subscribers")
        self.verify(c1)
        self.assertEqual(self.status(c1), "verified")
        rc, out, _ = self.R("edit", "--run", self.r, "--id", c1, "--text", "A has 95 mln subscribers")
        self.assertIn("pending", out)
        self.assertEqual(self.status(c1), "pending")
        self.assertIn("CHANGED since last verdict", self.R("list", "--run", self.r)[1])

    def test_inference_follows_its_premises(self):
        c1 = self.add("A has 81 mln subscribers")
        c2 = self.add("A is the largest operator", kind="inference", source="", locator="", defs="", depends=c1)
        self.verify(c1)
        self.verify(c2)
        self.assertEqual(self.status(c2), "verified")
        self.R("edit", "--run", self.r, "--id", c1, "--source", "https://x/other")
        self.assertEqual(self.status(c2), "pending")

    def test_calc_input_change_resets_status(self):
        data = self.d / "data.csv"
        data.write_text("a,1\n")
        script = self.d / "calc.py"
        script.write_text("print(1)\n")
        c1 = self.add("Total is 1", kind="calc", source=str(script), locator="line 1", inputs=str(data))
        self.verify(c1)
        data.write_text("a,2\n")
        self.assertEqual(self.status(c1), "pending")

    def test_verified_requires_verifier_and_report(self):
        c1 = self.add("A has 81 mln subscribers")
        rc, out, err = self.R("verdict", "--run", self.r, "--id", c1, "--status", "verified", "--by", "orchestrator")
        self.assertNotEqual(rc, 0)
        rc, out, err = self.R("verdict", "--run", self.r, "--id", c1, "--status", "verified", "--by", "fact-checker")
        self.assertNotEqual(rc, 0)

    # 3. text check and completion
    def test_check_catches_untraced_and_mismatched(self):
        c1 = self.add("A has 81 mln subscribers")
        self.verify(c1)
        cases = {
            "У компании 42 сотрудника.": "untraced",
            "Компания является лидером рынка.": "untraced",
            "У A 95 млн абонентов [{}].".format(c1): "number 95 not found",
            "Рынок вырос на 7% [~].": "contains numbers",
        }
        for text, expect in cases.items():
            f = self.d / "t.md"
            f.write_text(text + "\n")
            rc, out, _ = self.R("check", "--run", self.r, "--file", str(f))
            self.assertEqual(rc, 1, text)
            self.assertIn(expect, out, text)
        f.write_text("# Итог\n\nУ A 81 млн абонентов [{}]. Это хороший результат [~].\n".format(c1))
        rc, out, _ = self.R("check", "--run", self.r, "--file", str(f))
        self.assertEqual(rc, 0, out)

    def test_number_formats_match(self):
        c1 = self.add("Share is 28.5% (6 300 of 22,100 sites)", defs="LTE sites")
        self.verify(c1)
        f = self.d / "t.md"
        f.write_text("Доля 28,5% — 6300 из 22 100 площадок [{}].\n".format(c1))
        rc, out, _ = self.R("check", "--run", self.r, "--file", str(f))
        self.assertEqual(rc, 0, out)

    def test_done_only_through_finalize(self):
        rc, out, err = self.R("phase", "--run", self.r, "--set", "done")
        self.assertNotEqual(rc, 0)
        c1 = self.add("A has 81 mln subscribers")
        c2 = self.add("B has 40 mln subscribers", source="https://x/b")
        self.verify(c1)
        self.R("verdict", "--run", self.r, "--id", c2, "--status", "unverifiable", "--by", "orchestrator")
        draft = self.d / "draft.md"
        draft.write_text("У A 81 млн [{}]. У B 40 млн [{}]. Вывод [~].\n".format(c1, c2))
        self.report.unlink()
        rc, out, _ = self.R("finalize", "--run", self.r, "--file", str(draft))
        self.assertEqual(rc, 1)
        self.assertIn("no verifier report", out)
        self.report.write_text("ok\n")
        rc, out, _ = self.R("finalize", "--run", self.r, "--file", str(draft))
        self.assertEqual(rc, 0, out)
        final = (self.rp / "final.md").read_text()
        self.assertIn("[1]", final)
        self.assertIn("не подтверждено", final)
        self.assertNotIn("[C", final)
        self.assertNotIn("[~]", final)
        self.assertEqual(json.loads((self.rp / "state.json").read_text())["phase"], "done")

    def test_gate(self):
        self.add("A has 81 mln subscribers")
        self.R("phase", "--run", self.r, "--set", "verifying")
        out = self.R("hook-stop", stdin=json.dumps({"stop_hook_active": False}))[1]
        self.assertEqual(json.loads(out)["decision"], "block")
        self.assertEqual(self.R("hook-stop", stdin=json.dumps({"stop_hook_active": True}))[1].strip(), "")
        outs = [self.R("hook-stop", stdin="{}")[1].strip() for _ in range(5)]
        self.assertEqual(sum(1 for o in outs if o), 2)  # 3 blocks max in total


class UsageTest(unittest.TestCase):
    def test_ledger(self):
        d = Path(tempfile.mkdtemp())
        (d / ".conductor").mkdir()
        t = d / "t"
        (t / "s1" / "subagents").mkdir(parents=True)
        rec = lambda i, model, inp, out: json.dumps({"type": "assistant", "message": {
            "id": i, "model": model, "usage": {"input_tokens": inp, "output_tokens": out}}})
        (t / "s1.jsonl").write_text("\n".join([rec("m1", "claude-opus-5-5", 10, 5),
                                               rec("m1", "claude-opus-5-5", 10, 50),
                                               rec("m2", "claude-opus-5-5", 5, 100)]) + "\n")
        (t / "s1" / "subagents" / "agent-a1.jsonl").write_text(rec("s1", "claude-haiku-5-5", 3000, 800) + "\n")
        run("usage.py", ["hook-subagent-stop"], d, json.dumps({"agent_id": "a1", "agent_type": "conductor:scout"}))
        run("usage.py", ["hook-stop"], d, json.dumps({"session_id": "s1", "transcript_path": str(t / "s1.jsonl")}))
        snap = json.loads((d / ".conductor/usage/s1.json").read_text())
        self.assertEqual(snap["by_model"]["claude-opus-5-5"]["output_tokens"], 150)  # m1 deduplicated
        self.assertIn("conductor:scout (haiku)", snap["by_agent"])
        rc, out, _ = run("usage.py", ["report"], d)
        self.assertIn("Delegated share", out)


if __name__ == "__main__":
    unittest.main()
