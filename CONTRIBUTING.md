# Contributing to skill-seam

感谢关注。这是一个年轻的项目，以下约定是为了让改动可审、行为可预期。

## 开发环境

```bash
git clone https://github.com/Snow7-G/SkillSeam && cd skill-seam
python3 tests/test_atlas.py        # CLI 测试套件（纯标准库，无虚拟环境要求）
node tests/web_smoke.cjs           # 网页逻辑冒烟测试（node >= 18）
pip install pyyaml && python3 tests/differential_yaml.py  # 可选：块标量差分测试（dev-only）
```

## 硬性约定（PR 审查会卡这些）

1. **Prompt 双实现同步**：`skill_seam.py` 与 `docs/index.html` 里的 `SYSTEM_PROMPT`、
   `GEN_*_PROMPT`、一致率阈值（0.8）、冲突判定规则必须两边同时修改。
   两份文件头部有互指注释。只改一边的 PR 会被打回。
2. **隐私不变量**：任何落盘/输出的产物（`results.json`、`report.html`、任务草稿）
   不得包含本机绝对路径或用户名。`tests/test_atlas.py` 里有自动断言，请保持。
3. **[fatal] 解析问题阻止评测**：frontmatter 解析遇到无法可靠支持的语法（如折叠标量含更深缩进）时，以 `[fatal]` 前缀标记 issue，scan_skills 将其放入 rejected，主流程必须退出 2——不能带着可能错误的 description 继续评测。
4. **错误走 stderr，退出码契约**：`0` 无冲突 / `1` 有冲突 / `2` 配置或参数错误。
   capture 子命令例外：它必须吞掉一切异常并返回 0（不能打断用户会话）。
4. **新功能必须带测试**：`tests/test_atlas.py`（unittest）。涉及网页逻辑的改动
   同步更新 `tests/web_smoke.cjs`。

## 提交

- 小步提交，一个 PR 解决一件事
- commit message 用英文祈使句（`Add gray-pairs leak filter`），正文可中文
- 改动用户可见行为时，请同步更新 README 与 CHANGELOG.md
