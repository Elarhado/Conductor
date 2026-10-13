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
        run("runs.py", ["add", "--run", self.r, "--text", "A has 81 mln subs", "--source", "https://x/a",
                        "--locator", "p.3"], self.d)
        run("runs.py", ["add", "--run", self.r, "--text", "B renamed", "--source", "https://x/b"], self.d)
        run("runs.py", ["phase", "--run", self.r, "--set", "verifying"], self.d)

    def test_gate_blocks_then_allows(self):
        rc, out, _ = run("runs.py", ["hook-stop"], self.d, json.dumps({"stop_hook_active": False}))
        self.assertEqual(json.loads(out)["decision"], "block")
        rc, out, _ = run("runs.py", ["hook-stop"], self.d, json.dumps({"stop_hook_active": True}))
        self.assertEqual(out.strip(), "")
        run("runs.py", ["set", "--run", self.r, "--id", "C1", "--status", "verified"], self.d)
        run("runs.py", ["set", "--run", self.r, "--id", "C2", "--status", "unverifiable"], self.d)
        rc, out, _ = run("runs.py", ["hook-stop"], self.d, json.dumps({"stop_hook_active": False}))
        self.assertEqual(out.strip(), "")

    def test_gate_gives_up_after_limit(self):
        outs = [run("runs.py", ["hook-stop"], self.d, "{}")[1].strip() for _ in range(5)]
        self.assertEqual(sum(1 for o in outs if o), 3)

    def test_check_and_render(self):
        run("runs.py", ["set", "--run", self.r, "--id", "C1", "--status", "verified"], self.d)
        draft = write(self.d, "draft.md", "У A 81 млн абонентов [C1]. B сменил имя [C2].\n")
        rc, out, _ = run("runs.py", ["check", "--run", self.r, "--file", str(draft)], self.d)
        self.assertEqual(rc, 1)
        self.assertIn("[C2] is pending", out)
        run("runs.py", ["set", "--run", self.r, "--id", "C2", "--status", "unverifiable"], self.d)
        bad = write(self.d, "bad.md", "Рост составил 12,5% в 2025 году.\n")
        rc, out, _ = run("runs.py", ["check", "--run", self.r, "--file", str(bad)], self.d)
        self.assertEqual(rc, 1)
        self.assertIn("numbers without a claim reference", out)
        rc, out, _ = run("runs.py", ["render", "--run", self.r, "--file", str(draft), "--out",
                                     str(self.d / "final.md")], self.d)
        self.assertEqual(rc, 0, out)
        final = (self.d / "final.md").read_text()
        self.assertIn("[1]", final)
        self.assertIn("не подтверждено", final)
        self.assertIn("1. https://x/a — p.3", final)
        self.assertNotIn("[C", final)

    def test_unknown_marker_blocks(self):
        draft = write(self.d, "d.md", "Факт [C99].\n")
        rc, out, _ = run("runs.py", ["check", "--run", self.r, "--file", str(draft)], self.d)
        self.assertEqual(rc, 1)
        self.assertIn("does not exist", out)


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
