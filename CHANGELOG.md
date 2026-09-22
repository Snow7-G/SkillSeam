# Changelog

本项目的所有重要变更记录在此文件中。
格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本遵循 [SemVer](https://semver.org/lang/zh-CN/)。

## [Unreleased]

### Fixed
- CLI 在全部采样为 `ERROR` / `INVALID`（包括混合情况）时，保留诊断报告、向 stderr 提示评测失败并返回退出码 2，避免 CI 将失败评测视为通过（#1）。部分失败的判定策略不变。

## [0.1.0] - 2026-09-21

### Added
- CLI 检测核心：scan（frontmatter 解析与规范校验）→ 任务生成（LLM 自动生成正向/灰区问法，
  红队对抗框架 + 事故库 few-shot；LLM 挑选语义重叠技能对，失败回退 Dice 词面相似度）
  → 选择模拟（只注入 name+description 复现 agent 选择环境，n 次采样多数投票，
  一致率 <0.8 标记不稳定）→ 报告（SVG 混淆矩阵热力图、冲突明细与截胡关键词、修复建议改前/改后对照）。
- 退出码契约：0 无冲突 / 1 有冲突 / 2 配置或参数错误，可接 CI 门禁。
- 网页版（`docs/index.html`，单文件零依赖，可托管 GitHub Pages）：
  演示模式（内嵌真实运行数据）+ BYOK（OpenAI-compatible / OpenRouter / Gemini / Anthropic，
  key 仅存浏览器 localStorage）；任务自动生成与修复建议与 CLI 同源同规则。
- 真实问法沉淀：
  - `mark` 子命令：把真实事故标记进本地事故库（`~/.skill-seam/marked.jsonl`），
    检测时 `--with-marked` 自动合并（按当前技能集过滤）。
  - `capture` 子命令 + `--install-claude`：Claude Code `UserPromptSubmit` hook
    被动收集用户 prompt 到本地问法库（静默、幂等、可备份）。
  - `harvest` 子命令：从问法库 / Codex 会话日志收割真实问法，
    清洗去重、Dice 相关性排序，`--label` 可用 LLM 预标应选技能产出任务草稿。
- `export` 子命令：SKILL.md 目录 → 网页版粘贴格式。
- 测试：CLI 58 项（unittest，纯标准库）+ 网页逻辑冒烟 25 项（node）。
- CI：Python 3.10/3.12/3.13 测试矩阵 + 打包安装验证 + 网页冒烟。
