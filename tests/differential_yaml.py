#!/usr/bin/env python3
"""块标量解析差分测试：以 PyYAML 为 oracle 验证我们的手写子集（dev-only，CI 不跑）。

需要: pip install pyyaml（只装到临时目录亦可: pip install --target /tmp/pyyaml_oracle pyyaml）
运行: python3 tests/differential_yaml.py
覆盖: 样式(| >) × 收尾("" - +) × 尾部空行(0-3) × 内容形态（含开头/内部/尾部空行、全空块）。
折叠标量中的更深缩进为声明不支持的语法，仅验证其被标记为 [fatal]。
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
    for style, chomp in itertools.product(["|", ">"], ["", "-", "+"]):
        for trailer in [0, 1, 2, 3]:
            for body in [
                ["  line one", "  line two"],
                ["  line one", "", "  line two"],
                ["  line one", "", "", "", "  line two"],
                ["  line one"],
                ["", ""],
                ["", "  line one"],
            ]:
                fm_lines = [f"description: {style}{chomp}"] + body + [""] * trailer
                fm_doc = "\n".join(fm_lines) + "\n"
                text = "---\n" + fm_doc + "---\n\n正文\n"
                s, issues = ad.parse_frontmatter(text, Path("/x/a-b/SKILL.md"))
                fatal = any(i.startswith("[fatal]") for i in issues)
                expected = yaml.safe_load(fm_doc).get("description")
                total += 1
                if fatal:
                    if style == "|":
                        failures.append(("unexpected fatal (literal)", fm_doc))
                    continue  # 折叠更深缩进：声明不支持
                ours = s["description"] if s else None
                if ours != expected:
                    failures.append((f"ours={ours!r} yaml={expected!r}",
                                     f"{style}{chomp} trailer={trailer} body={body}"))
    print(f"differential: {total} cases, {len(failures)} mismatches")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
