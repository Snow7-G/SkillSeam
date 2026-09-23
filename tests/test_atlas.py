#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SkillSeam 全量测试。运行: python3 tests/test_atlas.py -v"""
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "skill_seam.py"
sys.path.insert(0, str(ROOT))
import skill_seam as ad  # noqa: E402


def run_cli(args, cwd=None):
    return subprocess.run([sys.executable, str(SCRIPT)] + args,
                          capture_output=True, text=True, cwd=cwd or str(ROOT))


class TestParser(unittest.TestCase):
    FM = "---\nname: {}\ndescription: {}\n---\n\n# 正文\n内容\n"

    def test_ok(self):
        s, issues = ad.parse_frontmatter(self.FM.format("a-b", "查询天气信息"),
                                         Path("/x/a-b/SKILL.md"))
        self.assertEqual(issues, [])
        self.assertEqual(s["name"], "a-b")
        self.assertEqual(s["body_lines"], 2)

    def test_missing_fm(self):
        s, issues = ad.parse_frontmatter("# 只有正文", Path("/x/a/SKILL.md"))
        self.assertIsNone(s)
        self.assertTrue(any("frontmatter" in i for i in issues))

    def test_unclosed_fm(self):
        s, issues = ad.parse_frontmatter("---\nname: a\n", Path("/x/a/SKILL.md"))
        self.assertIsNone(s)

    def test_invalid_name(self):
        _, issues = ad.parse_frontmatter(self.FM.format("A_B!", "描述"),
                                         Path("/x/A_B!/SKILL.md"))
        self.assertTrue(any("name 不符合规范" in i for i in issues))

    def test_name_dir_mismatch(self):
        _, issues = ad.parse_frontmatter(self.FM.format("a-b", "描述"),
                                         Path("/x/other-dir/SKILL.md"))
        self.assertTrue(any("不一致" in i for i in issues))

    def test_empty_desc(self):
        _, issues = ad.parse_frontmatter(self.FM.format("a-b", ""),
                                         Path("/x/a-b/SKILL.md"))
        self.assertTrue(any("description 为空" in i for i in issues))

    def test_overlong_desc(self):
        _, issues = ad.parse_frontmatter(self.FM.format("a-b", "长" * 1025),
                                         Path("/x/a-b/SKILL.md"))
        self.assertTrue(any("超长" in i for i in issues))

    def test_empty_body(self):
        text = "---\nname: a-b\ndescription: 描述\n---\n"
        _, issues = ad.parse_frontmatter(text, Path("/x/a-b/SKILL.md"))
        self.assertTrue(any("正文为空" in i for i in issues))

    def test_body_with_hr_not_truncated(self):
        """正文含 --- 水平线时不能被截断（回归：旧版用 split('--') 解析）。"""
        body = "第一段\n\n---\n\n第三段"
        text = f"---\nname: a-b\ndescription: 描述\n---\n\n{body}\n"
        s, issues = ad.parse_frontmatter(text, Path("/x/a-b/SKILL.md"))
        self.assertEqual(issues, [])
        self.assertEqual(s["body_lines"], body.count("\n") + 1)

    def test_long_body_warns(self):
        body = "\n".join(f"行{i}" for i in range(502))
        text = f"---\nname: a-b\ndescription: 描述\n---\n\n{body}\n"
        _, issues = ad.parse_frontmatter(text, Path("/x/a-b/SKILL.md"))
        self.assertTrue(any("500 行" in i for i in issues))

    def test_crlf_normalized(self):
        """Windows 换行的 frontmatter 不能让 name 尾部带 \\r。"""
        text = "---\r\nname: a-b\r\ndescription: 描述\r\n---\r\n\r\n# 正文\r\n内容"
        s, issues = ad.parse_frontmatter(text, Path("/x/a-b/SKILL.md"))
        self.assertEqual(issues, [])
        self.assertEqual(s["name"], "a-b")


class TestExtractChosen(unittest.TestCase):
    NAMES = ["a-b", "c-d"]

    def test_standard_json(self):
        self.assertEqual(ad.extract_chosen('{"chosen": "a-b"}', self.NAMES), "a-b")

    def test_fenced_json(self):
        self.assertEqual(ad.extract_chosen('```json\n{"chosen": "c-d"}\n```', self.NAMES), "c-d")

    def test_unquoted(self):
        self.assertEqual(ad.extract_chosen("chosen: a-b", self.NAMES), "a-b")

    def test_bare_name(self):
        self.assertEqual(ad.extract_chosen("a-b", self.NAMES), "a-b")

    def test_bare_none(self):
        self.assertEqual(ad.extract_chosen("NONE", self.NAMES), "NONE")

    def test_invalid_name(self):
        self.assertEqual(ad.extract_chosen('{"chosen": "nope"}', self.NAMES), "INVALID")

    def test_garbage(self):
        self.assertEqual(ad.extract_chosen("我觉得都行", self.NAMES), "INVALID")


class TestAggregate(unittest.TestCase):
    def setUp(self):
        self.saved = list(ad.TASKS)

    def tearDown(self):
        ad.TASKS.clear()
        ad.TASKS.extend(self.saved)

    def agg(self, votes, expected="a-b"):
        ad.TASKS.clear()
        ad.TASKS.extend([{"t": "任务", "e": expected, "kind": "positive"}])
        return ad.aggregate({(0, si): v for si, v in enumerate(votes)}, ["a-b", "c-d"])[0]

    def test_all_hit(self):
        r = self.agg(["a-b"] * 5)
        self.assertTrue(r["stable"] and not r["conflict"] and r["chosen"] == "a-b")

    def test_four_fifth_stable(self):
        r = self.agg(["a-b", "a-b", "a-b", "a-b", "c-d"])
        self.assertTrue(r["stable"] and not r["conflict"] and abs(r["consistency"] - 0.8) < 1e-9)

    def test_conflict(self):
        r = self.agg(["c-d"] * 5)
        self.assertTrue(r["conflict"] and r["chosen"] == "c-d")

    def test_error_not_conflict(self):
        r = self.agg(["ERROR"] * 5)
        self.assertFalse(r["stable"])
        self.assertFalse(r["conflict"])

    def test_invalid_majority_unstable(self):
        """INVALID 多数 = 工具侧解析失败，应归为不稳定而非冲突。"""
        r = self.agg(["INVALID"] * 5)
        self.assertFalse(r["stable"])
        self.assertFalse(r["conflict"])
        self.assertEqual(r["chosen"], "INVALID")

    def test_tie_unstable(self):
        r = self.agg(["a-b", "a-b", "c-d", "c-d", "NONE"])
        self.assertFalse(r["stable"])


class TestMark(unittest.TestCase):
    """事故标记：mark 子命令 + --with-marked 合并。"""

    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.lib = str(Path(self.td.name) / "marked.jsonl")

    def tearDown(self):
        self.td.cleanup()

    def mark(self, *args):
        return run_cli(["mark", "--library", self.lib] + list(args))

    def test_add_and_list(self):
        r = self.mark("复诊时查积分", "fuzhen-tixing")
        self.assertEqual(r.returncode, 0, msg=r.stdout)
        self.assertIn("已标记", r.stdout)
        r2 = self.mark("--list")
        self.assertIn("fuzhen-tixing", r2.stdout)
        self.assertIn("复诊时查积分", r2.stdout)

    def test_dedupe(self):
        self.mark("同一事故", "a-b")
        r = self.mark("同一事故", "a-b")
        self.assertEqual(r.returncode, 0)
        self.assertIn("已存在", r.stdout)
        lines = [l for l in Path(self.lib).read_text(encoding="utf-8").splitlines() if l.strip()]
        self.assertEqual(len(lines), 1)

    def test_invalid_skill_name(self):
        r = self.mark("任务", "坏名字!")
        self.assertEqual(r.returncode, 2)

    def test_with_marked_merge(self):
        with tempfile.TemporaryDirectory() as td:
            sdir, _ = make_clean_fixture(Path(td))  # tianqi-chaxun / canting-yuding
            self.mark("今天天气怎么样帮我看看", "tianqi-chaxun")
            self.mark("这条属于别的项目", "ghost-skill")  # 应被过滤
            r = run_cli([str(sdir), "--mock", "--with-marked", "--library", self.lib])
            self.assertEqual(r.returncode, 0, msg=r.stdout + r.stderr)
            self.assertIn("事故库合并: 纳入 1 条", r.stdout)
            results = json.loads((ROOT / "output" / "results.json").read_text(encoding="utf-8"))
            marked_rows = [x for x in results["rows"] if x["task"] == "今天天气怎么样帮我看看"]
            self.assertEqual(len(marked_rows), 1)

    def test_mark_skips_foreign_expected(self):
        """应选技能不在当前集合的事故被跳过而不是报错。"""
        with tempfile.TemporaryDirectory() as td:
            sdir, _ = make_clean_fixture(Path(td))
            self.mark("完全无关的事故", "ghost-skill")
            r = run_cli([str(sdir), "--mock", "--with-marked", "--library", self.lib])
            self.assertEqual(r.returncode, 0, msg=r.stdout + r.stderr)
            self.assertIn("跳过 1 条", r.stdout)


class TestCaptureHarvest(unittest.TestCase):
    """方案一：问法捕获 + 收割。"""

    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.queries = str(Path(self.td.name) / "queries.jsonl")

    def tearDown(self):
        self.td.cleanup()

    def capture_stdin(self, stdin_text, extra=None):
        return subprocess.run(
            [sys.executable, str(SCRIPT), "capture", "--queries", self.queries] + (extra or []),
            input=stdin_text, capture_output=True, text=True, cwd=str(ROOT))

    def test_capture_json_and_exit0(self):
        r = self.capture_stdin(json.dumps({"prompt": "帮我看看视力报告"}))
        self.assertEqual(r.returncode, 0)
        lines = [l for l in Path(self.queries).read_text(encoding="utf-8").splitlines() if l.strip()]
        self.assertEqual(len(lines), 1)
        self.assertIn("视力报告", lines[0])

    def test_capture_malformed_silent(self):
        """非法 stdin 也必须静默成功（捕获层是哑管道，只管追加）；原始文本兜底入库。"""
        r = self.capture_stdin("{{{not json")
        self.assertEqual(r.returncode, 0)
        r2 = self.capture_stdin("")
        self.assertEqual(r2.returncode, 0)
        lines = [l for l in Path(self.queries).read_text(encoding="utf-8").splitlines() if l.strip()]
        self.assertEqual(len(lines), 1)  # 空输入不落库，非空原始文本兜底落库

    def test_install_claude_hook_merges(self):
        settings = Path(self.td.name) / "settings.json"
        settings.write_text(json.dumps({
            "permissions": {"allow": ["Bash"]},
            "hooks": {"UserPromptSubmit": [{"hooks": [{"type": "command", "command": "existing-cmd"}]}]},
        }), encoding="utf-8")
        r = run_cli(["capture", "--install-claude", "--settings", str(settings)])
        self.assertEqual(r.returncode, 0, msg=r.stdout)
        data = json.loads(settings.read_text(encoding="utf-8"))
        self.assertIn("permissions", data)  # 原有配置保留
        ups = data["hooks"]["UserPromptSubmit"]
        cmds = [h["command"] for e in ups for h in e.get("hooks", [])]
        self.assertEqual(len(cmds), 2)  # existing + 新 hook
        self.assertTrue(any("skill_seam.py capture" in c for c in cmds))
        backups = list(Path(self.td.name).glob("settings.json.bak-*"))
        self.assertEqual(len(backups), 1)  # 有备份
        # 幂等：再装一次不重复
        r2 = run_cli(["capture", "--install-claude", "--settings", str(settings)])
        self.assertIn("已安装过", r2.stdout)
        data2 = json.loads(settings.read_text(encoding="utf-8"))
        ups2 = data2["hooks"]["UserPromptSubmit"]
        self.assertEqual(len(ups2), 2)

    def test_codex_parser_shapes(self):
        fixture = Path(self.td.name) / "session.jsonl"
        fixture.write_text("\n".join([
            json.dumps({"type": "message", "role": "user",
                        "content": [{"type": "input_text", "text": "帮我解读 OCT 报告"}]}),
            json.dumps({"payload": {"role": "user", "content": "纯字符串形式的消息"}}),
            json.dumps({"role": "assistant", "content": "助手回复不该被收进来"}),
            "not-json-line",
        ]), encoding="utf-8")
        qs = ad.collect_codex_queries(fixture.parent)
        joined = "\n".join(qs)
        self.assertIn("帮我解读 OCT 报告", joined)
        self.assertIn("纯字符串形式的消息", joined)
        self.assertNotIn("助手回复不该被收进来", joined)

    def test_harvest_e2e(self):
        with tempfile.TemporaryDirectory() as td:
            sdir, _ = make_clean_fixture(Path(td))
            qlib = Path(td) / "queries.jsonl"
            entries = [
                {"text": "今天天气怎么样帮我看看"},
                {"text": "明天会下雨吗，帮我查一下天气"},
                {"text": "帮我订一个四人桌的餐厅"},
                {"text": "重复的不会收两次", "dup": 1},
            ]
            qlib.write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in entries),
                            encoding="utf-8")
            qlib.write_text(qlib.read_text(encoding="utf-8") +
                            "\n" + json.dumps({"text": "今天天气怎么样帮我看看"}) + "\n")
            out = Path(td) / "draft.json"
            r = run_cli(["harvest", str(sdir), "--claude", "--queries", str(qlib),
                         "--out", str(out), "--limit", "10", "--min-len", "4"])
            self.assertEqual(r.returncode, 0, msg=r.stdout + r.stderr)
            drafts = json.loads(out.read_text(encoding="utf-8"))
            texts = [d["t"] for d in drafts]
            self.assertEqual(len(texts), len(set(texts)))  # 去重
            self.assertLessEqual(len(drafts), 10)
            self.assertTrue(all(d["e"] == "" for d in drafts))  # 未 label 时 e 为空
            self.assertGreaterEqual(len(drafts), 3)


class TestAdversarialPrompt(unittest.TestCase):
    """方案三：灰区生成改对抗式 + 事故库 few-shot。"""

    def setUp(self):
        self.saved = ad._gen_call
        self.prompts = []

    def tearDown(self):
        ad._gen_call = self.saved

    def fake_call(self, cfg, prompt):
        self.prompts.append(prompt)
        if "pairs" in prompt:
            return json.dumps({"pairs": [["a-b", "c-d"]]})
        if "任务问法" in prompt:
            return json.dumps(["普通正向任务"])
        if "红队" in prompt:
            return json.dumps({"first": ["攻击性问法A"], "second": ["攻击性问法B"]})
        return "[]"

    def test_attacker_prompt_and_fewshot(self):
        ad._gen_call = self.fake_call
        skills = [{"name": "a-b", "description": "甲的职责"},
                  {"name": "c-d", "description": "乙的职责"}]
        cfg = {"base_url": "http://x", "api_key": "k", "model": "m"}
        tasks, _ = ad.generate_tasks_real(cfg, skills, 1, 1,
                                          marked_examples=["这是真实事故问法样例"])
        gray_prompts = [p for p in self.prompts if "红队" in p]
        self.assertEqual(len(gray_prompts), 1)
        self.assertIn("这是真实事故问法样例", gray_prompts[0])  # few-shot 注入
        self.assertTrue(any(t["t"] == "攻击性问法A" and t["e"] == "a-b" for t in tasks))
        self.assertTrue(any(t["t"] == "攻击性问法B" and t["e"] == "c-d" for t in tasks))
        self.assertTrue(all("a-b" not in t["t"] and "c-d" not in t["t"] for t in tasks))


# 所有 provider 凭据相关的环境变量：测试构造「无配置」环境时必须一并清掉
PROVIDER_ENV_VARS = ("DASHSCOPE_API_KEY", "DEEPSEEK_API_KEY", "OPENAI_API_KEY",
                     "OPENAI_BASE_URL", "DEEPSEEK_BASE_URL", "ATLAS_MODEL")


def env_without_keys(**extra):
    env = {k: v for k, v in os.environ.items() if k not in PROVIDER_ENV_VARS}
    env.update(extra)
    return env


class TestReliabilityFixes(unittest.TestCase):
    """GPT-6 静态审查发现的 7 个问题中本批修复的 6 个。"""

    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.no_key_env = env_without_keys()

    def tearDown(self):
        self.td.cleanup()

    def test_no_config_requires_explicit_mock(self):
        """#1 无配置且无 --mock → 退出 2 并提示 --mock，不再静默降级。"""
        env = dict(self.no_key_env)
        r = subprocess.run([sys.executable, str(SCRIPT), str(ROOT / "demo-skills")],
                           capture_output=True, text=True, cwd=self.td.name, env=env)
        self.assertEqual(r.returncode, 2)
        self.assertIn("--mock", r.stderr)

    def test_explicit_mock_still_works(self):
        """#1 回归：显式 --mock 不受影响。"""
        r = subprocess.run([sys.executable, str(SCRIPT), str(ROOT / "demo-skills"),
                           "--demo-tasks", "--mock"],
                           capture_output=True, text=True, cwd=self.td.name, env=self.no_key_env)
        self.assertEqual(r.returncode, 1)  # demo 任务有冲突

    def _tasks_file(self, payload):
        tf = Path(self.td.name) / "tasks.json"
        tf.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return str(tf)

    def test_tasks_t_null(self):
        """t=null 不再被 str() 放过：指出条目与字段，退出 2。"""
        r = run_cli(["./demo-skills", "--tasks", self._tasks_file([{"t": None, "e": "tianqi-chaxun"}]), "--mock"])
        self.assertEqual(r.returncode, 2)
        self.assertIn("t(任务文本) 必须是非空字符串", r.stderr)

    def test_tasks_e_array(self):
        """e 为数组 → 退出 2。"""
        r = run_cli(["./demo-skills", "--tasks", self._tasks_file([{"t": "任务", "e": ["a"]}]), "--mock"])
        self.assertEqual(r.returncode, 2)
        self.assertIn("e(应选技能) 必须是非空字符串", r.stderr)

    def test_config_missing_fields(self):
        """配置只有 model → 一次性列出缺失字段，退出 2。"""
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / ".atlasrc.json").write_text(json.dumps({"model": "m"}), encoding="utf-8")
            env = env_without_keys()
            r = subprocess.run([sys.executable, str(SCRIPT), str(ROOT / "demo-skills")],
                               capture_output=True, text=True, cwd=td, env=env)
            self.assertEqual(r.returncode, 2)
            self.assertIn("base_url", r.stderr)
            self.assertIn("api_key", r.stderr)

    def test_config_not_object(self):
        env = env_without_keys()
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / ".atlasrc.json").write_text("[1,2]", encoding="utf-8")
            r = subprocess.run([sys.executable, str(SCRIPT), str(ROOT / "demo-skills")],
                               capture_output=True, text=True, cwd=td, env=env)
            self.assertEqual(r.returncode, 2)
            self.assertIn("JSON 对象", r.stderr)

    def test_out_dir_custom(self):
        """--out 把报告写到指定目录（与安装位置无关）。"""
        with tempfile.TemporaryDirectory() as td:
            outdir = Path(td) / "rep"
            r = run_cli(["./demo-skills", "--demo-tasks", "--mock", "--out", str(outdir)])
            self.assertEqual(r.returncode, 1)  # demo 任务含冲突：--out 生效的证明
            self.assertTrue((outdir / "report.html").exists())
            self.assertTrue((outdir / "results.json").exists())

    def test_none_expected_allowed(self):
        """e=NONE 是合法预期值，不被 unknown 校验拒绝。"""
        r = run_cli(["./demo-skills", "--tasks",
                     self._tasks_file([{"t": "zzzqqq", "e": "NONE"}]), "--mock"])
        self.assertEqual(r.returncode, 0, msg=r.stderr)

    def test_aggregate_none_expected(self):
        """预期 NONE：稳定选中某技能 = 过度接管冲突；选中 NONE = 正确。"""
        tasks = [{"t": "无关任务一", "e": "NONE", "kind": "positive"}]
        with patch.object(ad, "TASKS", tasks):
            votes = {(0, si): "baogao-jiedu" for si in range(ad.SAMPLES)}
            rows = ad.aggregate(votes, ["baogao-jiedu"])
            self.assertTrue(rows[0]["conflict"])
            votes = {(0, si): "NONE" for si in range(ad.SAMPLES)}
            rows = ad.aggregate(votes, ["baogao-jiedu"])
            self.assertFalse(rows[0]["conflict"])

    def test_tasks_null_item(self):
        """#3 [null] → 退出 2 并指明条目位置，不再 AttributeError。"""
        r = run_cli(["./demo-skills", "--tasks", self._tasks_file([None]), "--mock"])
        self.assertEqual(r.returncode, 2)
        self.assertIn("第 1 条不是 JSON 对象", r.stderr)

    def test_tasks_string_item(self):
        r = run_cli(["./demo-skills", "--tasks", self._tasks_file(["hello"]), "--mock"])
        self.assertEqual(r.returncode, 2)
        self.assertIn("第 1 条不是 JSON 对象", r.stderr)

    def test_tasks_missing_fields(self):
        r = run_cli(["./demo-skills", "--tasks", self._tasks_file([{"t": "只有任务"}]), "--mock"])
        self.assertEqual(r.returncode, 2)
        self.assertIn("e(应选技能) 必须是非空字符串", r.stderr)

    def test_frontmatter_folded_scalar(self):
        """#4 `>-` 折行拼接为单行，不再静默解析成 ">-"。"""
        text = "---\nname: a-b\ndescription: >-\n  Explain weather\n  forecasts for users\n---\n\n正文\n"
        s, issues = ad.parse_frontmatter(text, Path("/x/a-b/SKILL.md"))
        self.assertEqual(issues, [])
        self.assertEqual(s["description"], "Explain weather forecasts for users")

    def test_frontmatter_folded_blank_line(self):
        """#4 折叠模式：段间空行按规范产生换行（YAML 1.2.2 §6.5）。"""
        text = "---\nname: a-b\ndescription: >-\n  line one\n\n  line two\n---\n\n正文\n"
        s, issues = ad.parse_frontmatter(text, Path("/x/a-b/SKILL.md"))
        self.assertEqual(issues, [])
        self.assertEqual(s["description"], "line one\nline two")

    def test_frontmatter_literal_trailing_blank(self):
        """#4 `|`（clip）尾随空行剥离为单个末尾换行。"""
        text = "---\nname: a-b\ndescription: |\n  line one\n\n  line two\n\n---\n\n正文\n"
        s, issues = ad.parse_frontmatter(text, Path("/x/a-b/SKILL.md"))
        self.assertEqual(issues, [])
        self.assertEqual(s["description"], "line one\n\nline two\n")

    def test_frontmatter_strip_chomping(self):
        """#4 `|-` 无末尾换行。"""
        text = "---\nname: a-b\ndescription: |-\n  line one\n  line two\n---\n\n正文\n"
        s, issues = ad.parse_frontmatter(text, Path("/x/a-b/SKILL.md"))
        self.assertEqual(issues, [])
        self.assertEqual(s["description"], "line one\nline two")

    def test_frontmatter_keep_chomping(self):
        """#4 `|+` 保留末尾换行与空行。"""
        text = "---\nname: a-b\ndescription: |+\n  line one\n\n---\n\n正文\n"
        s, issues = ad.parse_frontmatter(text, Path("/x/a-b/SKILL.md"))
        self.assertEqual(issues, [])
        self.assertEqual(s["description"], "line one\n\n")

    def test_frontmatter_literal_preserves_extra_indent(self):
        """#4 字面标量保留块内额外缩进。"""
        text = "---\nname: a-b\ndescription: |-\n  line one\n    deeply indented\n---\n\n正文\n"
        s, issues = ad.parse_frontmatter(text, Path("/x/a-b/SKILL.md"))
        self.assertEqual(issues, [])
        self.assertEqual(s["description"], "line one\n  deeply indented")

    def test_frontmatter_folded_more_indent_unsupported(self):
        """#4 折叠标量中的更深缩进行：明确报错（不支持），不静默误解。"""
        text = "---\nname: a-b\ndescription: >-\n  line one\n    deeply indented\n---\n\n正文\n"
        _, issues = ad.parse_frontmatter(text, Path("/x/a-b/SKILL.md"))
        self.assertTrue(any("[fatal]" in i for i in issues))

    def test_frontmatter_tab_line_fatal(self):
        """frontmatter 中 Tab 开头的行 → fatal（YAML 禁止 Tab 缩进）。"""
        text = "---\nname: a-b\ndescription: d\n\tstray\n---\n\n正文\n"
        s, issues = ad.parse_frontmatter(text, Path("/x/a-b/SKILL.md"))
        self.assertIsNone(s)
        self.assertTrue(any("[fatal]" in i and "Tab" in i for i in issues))

    def test_fatal_blocks_evaluation(self):
        """验收点 3：不支持语法必须阻止评测并返回 2，不能继续当有效描述。"""
        with tempfile.TemporaryDirectory() as td:
            sdir = Path(td) / "bad-skill"
            (sdir / "bad-skill").mkdir(parents=True)
            (sdir / "bad-skill" / "SKILL.md").write_text(
                "---\nname: bad-skill\ndescription: >-\n  line one\n    deeply indented\n---\n\n正文\n",
                encoding="utf-8")
            r = run_cli([str(sdir), "--mock"])
            self.assertEqual(r.returncode, 2)
            self.assertIn("评测中止", r.stderr)

    def test_frontmatter_literal_scalar(self):
        """#4 `|`（clip）保留内容与一个末尾换行（YAML 1.2.2 §8.1.2）。"""
        text = "---\nname: a-b\ndescription: |\n  line one\n  line two\n---\n\n正文\n"
        s, issues = ad.parse_frontmatter(text, Path("/x/a-b/SKILL.md"))
        self.assertEqual(issues, [])
        self.assertEqual(s["description"], "line one\nline two\n")

    def test_frontmatter_stray_line_warns(self):
        """#4 无法解析的游离行产生警告而不是静默丢弃。"""
        text = "---\nname: a-b\ndescription: d\nsome stray line\n---\n\n正文\n"
        _, issues = ad.parse_frontmatter(text, Path("/x/a-b/SKILL.md"))
        self.assertTrue(any("无法解析的行" in i for i in issues))


class TestExport(unittest.TestCase):
    """export 子命令：SKILL.md 目录 → 网页粘贴格式。"""

    def test_export_demo(self):
        r = run_cli(["export", "./demo-skills"])
        self.assertEqual(r.returncode, 0, msg=r.stderr)
        lines = [l for l in r.stdout.splitlines() if l.strip()]
        self.assertEqual(len(lines), 6)
        self.assertTrue(all(": " in l for l in lines))
        self.assertTrue(any(l.startswith("guahao-yuyue: ") for l in lines))

    def test_export_missing(self):
        r = run_cli(["export", "/no/such/dir"])
        self.assertEqual(r.returncode, 2)


class TestConflictReason(unittest.TestCase):
    def test_lcs_keywords(self):
        """截胡关键词用最长公共子串：短语不需原样出现在任务里。"""
        thief = {"name": "c-d", "description": "受理视力检查、报告相关咨询的登记与转接"}
        row = {"chosen": "c-d", "task": "视力下降了，之前的报告还在吗？帮我查查。"}
        kw = ad.conflict_reason(row, {"c-d": thief})
        self.assertIn("视力", kw)
        self.assertIn("报告", kw)

    def test_no_common(self):
        thief = {"name": "c-d", "description": "完全无关的职责描述"}
        row = {"chosen": "c-d", "task": "完全不同的任务内容"}
        kw = ad.conflict_reason(row, {"c-d": thief})
        self.assertNotIn("完全无关的职责描述", kw)


class TestLlmPickPairs(unittest.TestCase):
    def setUp(self):
        self.skills = [{"name": n, "description": f"{n} 的职责"} for n in ("a-b", "c-d", "e-f")]
        self.saved_call = ad._gen_call

    def tearDown(self):
        ad._gen_call = self.saved_call

    def test_dedupe_and_order(self):
        ad._gen_call = lambda cfg, prompt: json.dumps(
            {"pairs": [["a-b", "c-d"], ["c-d", "a-b"], ["a-b", "ghost"], ["e-f", "a-b"]]})
        pairs = ad.llm_pick_pairs({}, self.skills, 3)
        names = [tuple(sorted((a["name"], b["name"]))) for a, b in pairs]
        self.assertEqual(names, [("a-b", "c-d"), ("a-b", "e-f")])

    def test_fallback_on_exception(self):
        def boom(cfg, prompt):
            raise RuntimeError("网络错误")
        ad._gen_call = boom
        self.assertEqual(ad.llm_pick_pairs({}, self.skills, 2), [])


class TestGenPositive(unittest.TestCase):
    def test_name_leak_filtered(self):
        """生成的任务文本里不能包含技能名（泄题会让模拟虚高）。"""
        saved = ad._gen_call
        ad._gen_call = lambda cfg, prompt: json.dumps(
            ["我想用foo-bar挂号", "帮我预约门诊"], ensure_ascii=False)
        try:
            skills = [{"name": "foo-bar", "description": "处理预约挂号"}]
            tasks, _ = ad.generate_tasks_real(
                {"base_url": "http://x", "api_key": "k", "model": "m"}, skills, 2, 0)
        finally:
            ad._gen_call = saved
        texts = [t["t"] for t in tasks]
        self.assertNotIn("我想用foo-bar挂号", texts)
        self.assertIn("帮我预约门诊", texts)


def make_clean_fixture(base: Path):
    """两个语义完全不相交的 skill + 分离的任务集，mock 下应全命中（退出码 0）。"""
    sdir = base / "skills"
    (sdir / "tianqi-chaxun").mkdir(parents=True)
    (sdir / "tianqi-chaxun" / "SKILL.md").write_text(
        "---\nname: tianqi-chaxun\ndescription: 查询城市天气预报与未来降雨信息\n---\n# 天气\n查询天气。\n",
        encoding="utf-8")
    (sdir / "canting-yuding").mkdir(parents=True)
    (sdir / "canting-yuding" / "SKILL.md").write_text(
        "---\nname: canting-yuding\ndescription: 预订餐厅座位与包间安排\n---\n# 订餐\n预订餐厅。\n",
        encoding="utf-8")
    tasks = [
        {"t": "今天北京天气怎么样？", "e": "tianqi-chaxun", "kind": "positive"},
        {"t": "明天会下雨吗？帮我查一下天气。", "e": "tianqi-chaxun", "kind": "positive"},
        {"t": "查一下后天有没有降雨。", "e": "tianqi-chaxun", "kind": "positive"},
        {"t": "帮我订一个四人桌的餐厅。", "e": "canting-yuding", "kind": "positive"},
        {"t": "今晚包间还有位置吗？帮我预订餐厅。", "e": "canting-yuding", "kind": "positive"},
        {"t": "预订周六晚上的餐厅座位。", "e": "canting-yuding", "kind": "positive"},
    ]
    tfile = base / "tasks.json"
    tfile.write_text(json.dumps(tasks, ensure_ascii=False), encoding="utf-8")
    return sdir, tfile


class TestCLIExitCodes(unittest.TestCase):
    def test_real_evaluation_exit_codes(self):
        cases = [
            ("request_errors", OSError("endpoint unavailable"), OSError("endpoint unavailable"), 2),
            ("invalid_responses", "not JSON", "not JSON", 2),
            ("mixed_failures", OSError("endpoint unavailable"), "not JSON", 2),
            ("correct", "tianqi-chaxun", "canting-yuding", 0),
            ("conflict", "canting-yuding", "canting-yuding", 1),
            ("none_is_valid", "NONE", "NONE", 1),
            ("partial_failure", "tianqi-chaxun", OSError("endpoint unavailable"), 0),
        ]
        for name, first, second, expected_code in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as td:
                sdir, tfile = make_clean_fixture(Path(td))
                tasks = json.loads(tfile.read_text(encoding="utf-8"))
                tasks = [tasks[0], tasks[-1]]
                tfile.write_text(json.dumps(tasks), encoding="utf-8")
                responses = {tasks[0]["t"]: first, tasks[1]["t"]: second}

                def chat_once(cfg, catalog, task_text):
                    response = responses[task_text]
                    if isinstance(response, Exception):
                        raise response
                    return response

                cfg = {"base_url": "https://example.invalid/v1", "model": "test-model",
                       "api_key": "YOUR_API_KEY_HERE"}
                old_cwd = os.getcwd()
                os.chdir(td)  # 输出目录基于 cwd：chdir 在所有 Python 版本行为一致
                try:
                    with patch.object(sys, "argv", [str(SCRIPT), str(sdir), "--tasks", str(tfile)]), \
                            patch.object(ad, "__file__", str(Path(td) / "skill_seam.py")), \
                            patch.object(ad, "TASKS", []), \
                            patch.object(ad, "load_config", return_value=cfg), \
                            patch.object(ad, "chat_once", side_effect=chat_once), \
                            patch.object(ad.time, "sleep"), \
                            patch.object(ad, "generate_fix_suggestions", return_value=[]), \
                            patch.object(sys, "stdout", new_callable=io.StringIO), \
                            patch.object(sys, "stderr", new_callable=io.StringIO) as stderr:
                        with self.assertRaises(SystemExit) as result:
                            ad.main()
                        self.assertEqual(result.exception.code, expected_code)
                        if expected_code == 2:
                            self.assertIn("评测失败", stderr.getvalue())
                        else:
                            self.assertEqual(stderr.getvalue(), "")
                finally:
                    os.chdir(old_cwd)
                results = json.loads((Path(td) / "output" / "results.json").read_text(encoding="utf-8"))
                self.assertEqual(len(results["rows"]), 2)
                for row, response in zip(results["rows"], (first, second)):
                    vote = "ERROR" if isinstance(response, Exception) else ad.extract_chosen(
                        response, ["tianqi-chaxun", "canting-yuding"])
                    self.assertEqual(row["votes"], [vote] * ad.SAMPLES)
                self.assertTrue((Path(td) / "output" / "report.html").exists())

    def test_none_overtake_real_mode(self):
        """预期 NONE 的过度接管：真实模式下建议生成不崩溃，冲突保留，退出 1。"""
        with tempfile.TemporaryDirectory() as td:
            sdir, tfile = make_clean_fixture(Path(td))
            tasks = json.loads(tfile.read_text(encoding="utf-8"))
            tasks = [dict(tasks[0], e="NONE"), tasks[-1]]
            tfile.write_text(json.dumps(tasks), encoding="utf-8")
            responses = {tasks[0]["t"]: "canting-yuding", tasks[1]["t"]: "canting-yuding"}

            def chat_once(cfg, catalog, task_text):
                return responses[task_text]

            cfg = {"base_url": "https://example.invalid/v1", "model": "test-model",
                   "api_key": "x"}
            old_cwd = os.getcwd()
            os.chdir(td)
            try:
                with patch.object(sys, "argv", [str(SCRIPT), str(sdir), "--tasks", str(tfile)]), \
                        patch.object(ad, "TASKS", []), \
                        patch.object(ad, "load_config", return_value=cfg), \
                        patch.object(ad, "chat_once", side_effect=chat_once), \
                        patch.object(ad, "_gen_call") as gen_mock, \
                        patch.object(ad.time, "sleep"), \
                        patch.object(sys, "stdout", new_callable=io.StringIO), \
                        patch.object(sys, "stderr", new_callable=io.StringIO):
                    with self.assertRaises(SystemExit) as result:
                        ad.main()
                    self.assertEqual(result.exception.code, 1)
                    self.assertEqual(gen_mock.call_count, 0)  # 冲突已被过滤，不会发起建议生成请求
            finally:
                os.chdir(old_cwd)
            results = json.loads((Path(td) / "output" / "results.json").read_text(encoding="utf-8"))
            overtake = [r for r in results["rows"] if r["expected"] == "NONE"]
            self.assertEqual(len(overtake), 1)
            self.assertTrue(overtake[0]["conflict"])
            self.assertTrue((Path(td) / "output" / "report.html").exists())

    def test_deepseek_env_fallback(self):
        """DEEPSEEK_API_KEY 走官方端点（此前只支持 DashScope/OpenAI）。"""
        env = env_without_keys(DEEPSEEK_API_KEY="sk-test-deepseek")
        with tempfile.TemporaryDirectory() as td:
            r = subprocess.run([sys.executable, str(SCRIPT), str(ROOT / "demo-skills"),
                                "--demo-tasks", "--mock"], capture_output=True, text=True,
                               cwd=td, env=env)
            self.assertEqual(r.returncode, 1, msg=r.stderr)  # mock 模式跑通（demo 有冲突）
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "sk-test-deepseek"}, clear=True):
            c = ad.load_config()
        self.assertEqual(c["base_url"], "https://api.deepseek.com/v1")
        self.assertEqual(c["model"], "deepseek-chat")
        self.assertEqual(c["api_key"], "sk-test-deepseek")

    def test_scan_is_recursive_and_skips_hidden(self):
        """递归查找 SKILL.md（支持分类嵌套），但跳过隐藏目录（.system/.git）。"""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "skills"
            for rel in ("flat-a/SKILL.md", "category/deep-b/SKILL.md", ".system/sys-c/SKILL.md",
                        ".git/git-d/SKILL.md", "node_modules/nm-e/SKILL.md"):
                p = root / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(f"---\nname: {rel.split('/')[0].strip('.')}\ndescription: d\n---\n",
                             encoding="utf-8")
            skills, issues, rejected = ad.scan_skills(root)
            names = sorted(s["name"] for s in skills)
            self.assertEqual(names, ["category", "flat-a"])       # 嵌套被找到，隐藏/噪音被跳过
            self.assertEqual(rejected, [])
            self.assertTrue(any("跳过 3 个" in " ".join(msgs) for _, msgs in issues))

    def test_all_requests_fail_reports_reason(self):
        """全部请求失败时必须给出具体原因与排查方向，而不是笼统的「评测失败」。"""
        def boom(cfg, catalog, task_text):
            raise RuntimeError("simulated 429 too many requests")

        with tempfile.TemporaryDirectory() as td:
            sdir, tfile = make_clean_fixture(Path(td))
            cfg = {"base_url": "https://example.invalid/v1", "model": "m", "api_key": "x"}
            old_cwd = os.getcwd()
            os.chdir(td)
            try:
                with patch.object(sys, "argv", [str(SCRIPT), str(sdir), "--tasks", str(tfile)]), \
                        patch.object(ad, "load_config", return_value=cfg), \
                        patch.object(ad, "chat_once", side_effect=boom), \
                        patch.object(ad.time, "sleep"), \
                        patch.object(sys, "stdout", new_callable=io.StringIO), \
                        patch.object(sys, "stderr", new_callable=io.StringIO) as stderr:
                    with self.assertRaises(SystemExit) as result:
                        ad.main()
                    err = stderr.getvalue()
                    self.assertEqual(result.exception.code, 2)
                    self.assertIn("simulated 429", err)      # 原始异常原因透出
                    self.assertIn("--workers", err)          # 给出降并发建议
            finally:
                os.chdir(old_cwd)

    def test_workers_flag_accepted(self):
        """--workers 的值不能被当成技能目录参数。"""
        r = run_cli(["./demo-skills", "--demo-tasks", "--mock", "--workers", "2"])
        self.assertEqual(r.returncode, 1, msg=r.stderr)   # demo 任务含冲突
        self.assertNotIn("没有 SKILL.md", r.stderr)

    def test_export_flattens_multiline_description(self):
        """export 必须输出单行 name: description（| 块标量的多行描述要折叠）。"""
        with tempfile.TemporaryDirectory() as td:
            sdir = Path(td) / "m"
            (sdir / "multi-line").mkdir(parents=True)
            (sdir / "multi-line" / "SKILL.md").write_text(
                "---\nname: multi-line\ndescription: |\n  line one\n  line two\n---\n\n正文\n",
                encoding="utf-8")
            (sdir / "plain").mkdir()
            (sdir / "plain" / "SKILL.md").write_text(
                "---\nname: plain\ndescription: 普通描述\n---\n\n正文\n", encoding="utf-8")
            r = run_cli(["export", str(sdir)])
            self.assertEqual(r.returncode, 0, msg=r.stderr)
            out_lines = [l for l in r.stdout.splitlines() if l.strip()]
            self.assertEqual(len(out_lines), 2, msg=r.stdout)  # 每技能恰好一行
            self.assertIn("multi-line: line one line two", out_lines)

    def test_missing_dir(self):
        self.assertEqual(run_cli(["/no/such/dir", "--mock"]).returncode, 2)

    def test_empty_dir(self):
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "empty").mkdir()
            self.assertEqual(run_cli([str(Path(td) / "empty"), "--mock"]).returncode, 2)

    def test_tasks_file_missing(self):
        self.assertEqual(run_cli(["./demo-skills", "--tasks", "/no/tasks.json", "--mock"]).returncode, 2)

    def test_tasks_file_malformed_json(self):
        with tempfile.TemporaryDirectory() as td:
            tf = Path(td) / "bad.json"
            tf.write_text("{not json", encoding="utf-8")
            r = run_cli(["./demo-skills", "--tasks", str(tf), "--mock"])
            self.assertEqual(r.returncode, 2)
            self.assertIn("合法 JSON", r.stderr)

    def test_tasks_file_not_array(self):
        with tempfile.TemporaryDirectory() as td:
            tf = Path(td) / "obj.json"
            tf.write_text('{"t": "任务", "e": "x"}', encoding="utf-8")
            r = run_cli(["./demo-skills", "--tasks", str(tf), "--mock"])
            self.assertEqual(r.returncode, 2)
            self.assertIn("JSON 数组", r.stderr)

    def test_tasks_unknown_expected(self):
        """应选技能不存在时报错退出 2，而不是渲染时崩溃。"""
        with tempfile.TemporaryDirectory() as td:
            tf = Path(td) / "tasks.json"
            tf.write_text(json.dumps([{"t": "任意任务", "e": "ghost-skill"}], ensure_ascii=False),
                          encoding="utf-8")
            r = run_cli(["./demo-skills", "--tasks", str(tf), "--mock"])
            self.assertEqual(r.returncode, 2)
            self.assertIn("ghost-skill", r.stderr)

    def test_clean_fixture_zero(self):
        with tempfile.TemporaryDirectory() as td:
            sdir, tfile = make_clean_fixture(Path(td))
            r = run_cli([str(sdir), "--tasks", str(tfile), "--mock"])
            self.assertEqual(r.returncode, 0, msg=r.stdout + r.stderr)

    def test_demo_builtin_conflict_one(self):
        """内置 demo 任务 + demo-skills = 已知撞车 → 退出码 1。"""
        self.assertEqual(run_cli(["./demo-skills", "--demo-tasks", "--mock"]).returncode, 1)

    def test_mock_autogen_zero(self):
        """默认自动生成（mock）+ 语义不相交的 fixture → 全命中，退出码 0。"""
        with tempfile.TemporaryDirectory() as td:
            sdir, _ = make_clean_fixture(Path(td))
            r = run_cli([str(sdir), "--mock"])
            self.assertEqual(r.returncode, 0, msg=r.stdout + r.stderr)
            gen = json.loads((ROOT / "output" / "tasks-generated.json").read_text(encoding="utf-8"))
            self.assertEqual(len(gen), 10)  # 2 skills × 5 正向；语义不相交 → 无灰区对

    def test_gray_pairs_zero(self):
        """--gray-pairs 0 = 明确不要灰区任务（即使是相似技能也不生成）。"""
        with tempfile.TemporaryDirectory() as td:
            sdir, _ = make_clean_fixture(Path(td))
            r = run_cli([str(sdir), "--mock", "--gray-pairs", "0"])
            self.assertEqual(r.returncode, 0, msg=r.stdout + r.stderr)
            gen = json.loads((ROOT / "output" / "tasks-generated.json").read_text(encoding="utf-8"))
            self.assertTrue(all(t["kind"] == "positive" for t in gen))


class TestOutputArtifacts(unittest.TestCase):
    """跑一次 mock 全量，校验产物结构与隐私。"""

    @classmethod
    def setUpClass(cls):
        cls.r = run_cli(["./demo-skills", "--demo-tasks", "--mock"])
        cls.results = json.loads((ROOT / "output" / "results.json").read_text(encoding="utf-8"))
        cls.html = (ROOT / "output" / "report.html").read_text(encoding="utf-8")

    def test_run_ok(self):
        self.assertIn("摘要", self.r.stdout)

    def test_results_schema(self):
        rows = self.results["rows"]
        self.assertEqual(len(rows), 40)
        for row in rows:
            self.assertEqual(len(row["votes"]), 5)
            top, cnt = Counter(row["votes"]).most_common(1)[0]
            self.assertEqual(top, row["chosen"])
            self.assertAlmostEqual(row["consistency"], cnt / 5)
        self.assertEqual(len(self.results["tasks"]), 40)

    def test_no_privacy_leak(self):
        raw = json.dumps(self.results, ensure_ascii=False)
        self.assertNotIn("/Users/", raw)
        self.assertNotIn("w1nstep", raw)
        self.assertNotIn("/Users/", self.html)
        for s in self.results["meta"]["skills"]:
            self.assertNotIn("path", s)

    def test_report_structure(self):
        for anchor in ("选择混淆矩阵", "冲突明细", "SkillSeam"):
            self.assertIn(anchor, self.html)
        svg = self.html[self.html.index("<svg"):self.html.index("</svg>") + 6]
        ET.fromstring(svg)  # SVG 必须是合法 XML

    def test_fix_section_rendering(self):
        """有冲突 + 有建议 → 渲染修复区块；改写文本转义；无建议 → 显示手动指引。"""
        rows = [{"id": 0, "task": "任务<一>", "expected": "a-b", "kind": "positive",
                 "pair": "", "votes": ["c-d"] * 5, "chosen": "c-d",
                 "consistency": 1.0, "stable": True, "conflict": True}]
        skills = [{"name": "a-b", "description": "甲的职责"}, {"name": "c-d", "description": "乙的职责<含尖号>"}]
        meta = {"mode_label": "测试", "model": "m", "fix_suggestions": [
            {"victim": "a-b", "thief": "c-d", "conflict_tasks": ["任务<一>"],
             "changes": [{"skill": "c-d", "new_description": "乙的职责 & 边界词", "reason": "加边界"}]}]}
        html = ad.render_report(rows, skills, meta)
        self.assertIn("修复建议", html)
        self.assertIn("乙的职责 &amp; 边界词", html)   # 改写内容被转义
        self.assertIn("任务&lt;一&gt;", html)           # 任务文本被转义
        html_nofix = ad.render_report(rows, skills, {"mode_label": "t", "model": "m"})
        self.assertIn("未能自动生成建议", html_nofix)

    def test_mock_determinism(self):
        first = json.loads(json.dumps(self.results))
        run_cli(["./demo-skills", "--demo-tasks", "--mock"])
        second = json.loads((ROOT / "output" / "results.json").read_text(encoding="utf-8"))
        first["meta"].pop("generated_at")
        second["meta"].pop("generated_at")
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main(verbosity=2)
