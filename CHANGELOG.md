# Changelog

本项目的所有重要变更记录在此文件中。
格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本遵循 [SemVer](https://semver.org/lang/zh-CN/)。

## [Unreleased]

### Added
- 网页版「选择技能文件夹」：纯前端读取本机技能目录，自动解析所有 SKILL.md 的 name/description 并填入输入框（浏览器内解析，不上传任何文件）。支持 `>` 折行与 `|` 字面块标量、引号值、缺 name 时回退目录名；无 SKILL.md、缺 description 等情形给出明确提示。

### Fixed
- `export` 输出的 description 现在折叠为单行（`|` 块标量的多行描述此前会破坏"每行一条"的粘贴格式）。

### Added
- 网页整体美化：CSS 设计令牌化（间距节拍 4/8/12/16/24、行高统一 1.6-1.65、圆角三级体系），卡片增加细腻投影，按钮/输入框补齐 hover 与 focus 态，矩阵区域支持横向滚动；全程纯色无渐变。

### Added
- 网页 UI 美化：技能名统一渲染为玻璃质感胶囊——冲突明细、未标注任务、修复建议、演示模式、混淆矩阵行标签（标签列宽随最长名字动态扩展，不再裁切）；结果卡新增「已识别技能」胶囊条；矩阵列头超长截断并支持悬浮显示完整名。

### Added
- 任务预期值支持 `NONE`（量化"过度接管"：无关任务被哪个 skill 错误接管）；混淆矩阵新增 NONE 行；网页同步支持 `=> NONE`（issue #3）。
- 网页单请求 90 秒应用层超时（AbortController），新增「停止评测」按钮，停止后结果明确标记不完整。
- CLI `--out` 选项：报告输出目录可指定，默认当前工作目录的 `output/`（不再写入安装位置）。
- CI 新增块标量差分 job（PyYAML 作 oracle，dev-only，运行时零依赖不变）。

### Fixed
- 任务字段与模型配置按类型校验：`t: null`、`e: []`、配置缺 `base_url` 等一律退出 2 并列出明细，不再 `AttributeError`/`KeyError` 后以退出码 1 混入冲突信号。

### Fixed
- 缺少模型配置时不再静默降级为 mock：无配置且未显式指定 `--mock` 时退出码 2 并提示（避免 CI 误判通过）。
- 任务文件元素类型校验：`[null]` 等非法条目返回退出码 2 并指明条目位置，不再抛 `AttributeError`。
- frontmatter 按原始行边界提取，支持 YAML 块标量（`>` / `|`），折行与收尾规则（clip/strip/keep）符合 YAML 1.2.2 §6.5/§8.1.2；块标量中的 Tab 与折叠标量中的更深缩进暂不支持（显式拒绝并退出 2）。手写实现保持零依赖，PyYAML 差分测试背书（268 组合，支持/拒绝分组验证）。
- 无法可靠解析的 frontmatter 语法升级为致命错误（阻止评测并返回 2）：块标量头行内注释 / 显式缩进指示符、折叠标量中的更深缩进或 Tab 行、frontmatter 中 Tab 开头的行；闭合围栏必须在行首（块标量内容中的缩进 `---` 不再被误认为围栏）。
- 网页版：全部选择结果不可解析时明确显示"评测失败"，不再给出"无冲突"结论。
- 网页版：取消"记住配置"时清除已保存的配置与 Key（此前只停止后续保存）。
- README 的 CI 示例移除 `|| echo`（echo 会吞掉退出码导致 CI 误判通过）。

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
