#!/usr/bin/env python3
"""块标量解析差分测试：以 PyYAML 为 oracle 验证手写子集。

运行: python tests/differential_yaml.py（CI 会安装 PyYAML 运行本脚本；运行时零依赖不变）

两组用例，计数分开输出：
- 支持组：必须无 [fatal]，且结果与 PyYAML 完全一致。
  含字面标量的全部空白形态（超缩进空白/Tab 是内容，精确保留）。
- 拒绝组：声明不支持的语法，必须产生 [fatal]（由 test_fatal_blocks_evaluation
  保证 CLI 层退出 2 阻止评测）。含折叠标量更深缩进/Tab 行、头行注释、显式缩进指示符。
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


def classify(style, body):
    """按声明支持的范围预分类：'support' 或 'reject: 原因'。"""
    if any("\t" in l for l in body):
        return "reject: 块标量含 Tab（不支持，显式拒绝）"
    if style == "|":
        return "support"  # 字面标量：全部空白形态精确保留
    non_ws = [l for l in body if l.strip()]
    base = min((len(l) - len(l.lstrip(" ")) for l in non_ws), default=2)
    for l in body:
        if l.strip() == "":
            if len(l) > base:
                return "reject: 折叠标量含超缩进空白行"
            continue
        text = l[base:]
        if text.startswith((" ", "\t")):
            return "reject: 折叠标量含更深缩进行"
    return "support"


def main():
    support_total = reject_total = 0
    support_fail, reject_fail = [], []

    bodies = [
        ["  line one", "  line two"],                # 相邻两行
        ["  line one", "", "  line two"],            # 段间空行
        ["  line one", "", "", "", "  line two"],    # 多个空行
        ["  line one"],                              # 单行
        ["", ""],                                    # 全空块
        ["", "  line one"],                          # 开头空行
        ["  line one", "    ", "  line two"],        # 纯空白行(超缩进)
        ["  line one", "  ", "  line two"],          # 纯空白行(恰为缩进)
        ["  first", "    "],                         # 尾部超缩进空白
        ["  first", "  \t", "  last"],               # 尾部含 Tab 的空白行
        ["  line one", "\tdeep", "  last"],          # 中间 Tab 开头行
    ]
    for style, chomp in itertools.product(["|", ">"], ["", "-", "+"]):
        for trailer in [0, 1, 2, 3]:
            for body in bodies:
                group = classify(style, body)
                fm_lines = [f"description: {style}{chomp}"] + body + [""] * trailer
                fm_doc = "\n".join(fm_lines) + "\n"
                text = "---\n" + fm_doc + "---\n\n正文\n"
                s, issues = ad.parse_frontmatter(text, Path("/x/a-b/SKILL.md"))
                fatal = any(i.startswith("[fatal]") for i in issues)
                try:
                    expected = yaml.safe_load(fm_doc).get("description")
                except yaml.YAMLError:
                    expected = None  # oracle 也拒绝 → 双方一致拒绝
                if group.startswith("reject"):
                    reject_total += 1
                    if not fatal:
                        ours = s["description"] if s else None
                        reject_fail.append((f"未拒绝（ours={ours!r}）", f"{style}{chomp} trailer={trailer} body={body}"))
                    continue
                support_total += 1
                if fatal:
                    support_fail.append(("支持组意外 fatal", fm_doc))
                    continue
                ours = s["description"] if s else None
                if ours != expected:
                    support_fail.append((f"ours={ours!r} yaml={expected!r}",
                                         f"{style}{chomp} trailer={trailer} body={body}"))

    # 拒绝组补充：头行形态不支持（行内注释 / 显式缩进指示符）
    for header in ["description: >- # explanation", "description: |2-"]:
        for body in [["  weather: forecast"], ["  line one"]]:
            fm_lines = [header] + body
            fm_doc = "\n".join(fm_lines) + "\n"
            text = "---\n" + fm_doc + "---\n\n正文\n"
            _, issues = ad.parse_frontmatter(text, Path("/x/a-b/SKILL.md"))
            reject_total += 1
            if not any(i.startswith("[fatal]") for i in issues):
                reject_fail.append((f"头行未拒绝: {header}", fm_doc))

    print(f"differential: 支持组 {support_total}（失败 {len(support_fail)}），"
          f"拒绝组 {reject_total}（失败 {len(reject_fail)}）")
    for label, detail in support_fail + reject_fail[:6]:
        print("  FAIL:", label, "|", detail)
    sys.exit(1 if (support_fail or reject_fail) else 0)


if __name__ == "__main__":
    main()
