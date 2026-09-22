#!/usr/bin/env python3
"""块标量解析差分测试：以 PyYAML 为 oracle 验证手写子集（dev-only，CI 不跑）。

需要: pip install pyyaml（可装到隔离目录后用 PYTHONPATH 指向）
运行: python3 tests/differential_yaml.py

两组用例：
- 支持组：必须无 [fatal]，且结果与 PyYAML 完全一致。
- 拒绝组：声明不支持的语法（折叠标量更深缩进/Tab、头行注释、显式缩进指示符），
  必须产生 [fatal]（由 test_fatal_blocks_evaluation 保证 CLI 层退出 2）。
"""
import itertools
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import skill_seam as ad  # noqa: E402

try:
    import yaml
except ImportError:
    print("需要 PyYAML 做 oracle：pip install pyyaml")
    sys.exit(2)


def main():
    failures, total = [], 0

    def run_case(fm_lines, group):
        nonlocal total
        fm_doc = "\n".join(fm_lines) + "\n"
        text = "---\n" + fm_doc + "---\n\n正文\n"
        s, issues = ad.parse_frontmatter(text, Path("/x/a-b/SKILL.md"))
        fatal = any(i.startswith("[fatal]") for i in issues)
        total += 1
        return fm_doc, s, issues, fatal

    # ---------- 支持组 ----------
    for style, chomp in itertools.product(["|", ">"], ["", "-", "+"]):
        for trailer in [0, 1, 2, 3]:
            for body in [
                ["  line one", "  line two"],
                ["  line one", "", "  line two"],
                ["  line one", "", "", "", "  line two"],
                ["  line one"],
                ["", ""],
                ["", "  line one"],
                ["  line one", "    ", "  line two"],       # 纯空白行(超出缩进)
                ["  line one", "  ", "  line two"],          # 纯空白行(恰为缩进)
                ["  line one", "  ", "", "  last"],          # 混合
            ]:
                fm_lines = [f"description: {style}{chomp}"] + body + [""] * trailer
                fm_doc, s, issues, fatal = run_case(fm_lines, "support")
                if fatal:
                    failures.append(("支持组出现 fatal", fm_doc, issues))
                    continue
                expected = yaml.safe_load(fm_doc).get("description")
                ours = s["description"] if s else None
                if ours != expected:
                    failures.append((f"ours={ours!r} yaml={expected!r}",
                                     f"{style}{chomp} trailer={trailer} body={body} fm={fm_doc!r}"))

    # ---------- 拒绝组（声明不支持，必须 fatal）----------
    reject_cases = [
        (["description: >-", "  line one", "    deeply indented"], "折叠更深缩进"),
        (["description: >-", "  line one", "\tdeeply indented"], "折叠 Tab 缩进"),
        (["description: >- # explanation", "  weather: forecast"], "头行行内注释"),
        (["description: |2-", "  weather: forecast"], "显式缩进指示符"),
    ]
    for body, why in reject_cases:
        fm_doc, s, issues, fatal = run_case(body, "reject")
        total += 1
        if not fatal:
            ours = s["description"] if s else None
            failures.append((f"拒绝组未 fatal: {why}, ours={ours!r}", fm_doc))

    print(f"differential: {total} cases, {len(failures)} mismatches")
    for f in failures[:12]:
        print("  FAIL:", f[0])
        if len(f) > 2:
            print("        input:", f[2] if isinstance(f[2], str) else f[1:])
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
