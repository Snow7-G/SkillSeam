# SkillSeam

[English](README.md) | **简体中文** | [日本語](README.ja.md) | [한국어](README.ko.md) | [Español](README.es.md) | [Deutsch](README.de.md)

<p align="center">
  <img src="assets/banner.svg" alt="SkillSeam" width="720">
</p>

[![CI](https://github.com/Snow7-G/SkillSeam/actions/workflows/ci.yml/badge.svg)](https://github.com/Snow7-G/SkillSeam/actions/workflows/ci.yml) [![License: MIT](https://img.shields.io/badge/License-MIT-0f6e56.svg)](LICENSE) [![Python](https://img.shields.io/badge/Python-3.10%2B-0f6e56.svg)](pyproject.toml) [![Tests](https://img.shields.io/badge/Tests-98%20passing-3b6d11.svg)](tests/test_atlas.py)

模拟 agent 真实挑选 skill 的过程，找出哪个 skill 抢了谁的活。在用户发现问题之前。

## 问题在哪

Claude Code、Codex 这类 agent 加载 skill 时只读一两行 description。任务来了，agent 挑听起来最像的那个。

两个 description 不重叠时没问题。一旦重叠就有事。我们医院项目里，挂号预约的 description 写了"受理视力检查、报告相关咨询"，而报告解读才是真正管这事的。病人要解读报告，agent 把话递给了挂号 skill，挂号 skill 开始瞎编。不报错，不留日志。最后是病人投诉了才知道。

SkillSeam 把这个选择过程搬到上线之前重演。内置的两套 demo 都是 6 个眼科客服 skill、40 条任务的真实运行——中文集暴露 4 处边界问题，英文集 6 处，每一处都是一致率 5/5、无摇摆行。每条冲突报告都会指出截胡方 description 里惹祸的关键词。

## 快速开始（网页版，零安装）

打开 https://snow7-g.github.io/SkillSeam/?lang=zh ，点「看演示数据」，十秒出热力图。然后点「选择技能文件夹」直接选你的技能目录（浏览器内解析，不上传任何文件），或用 `python3 skill_seam.py export ~/.agents/skills` 拿到粘贴格式，填 API key（只存你的浏览器，请求直达端点），点「开始模拟」。

英文界面（`?lang=en`）配的是另一套英文 demo 数据集，也来自仓库内存档的真实运行。复现：

```bash
python3 skill_seam.py demo-skills-en --tasks examples/tasks-demo-en.json
```

支持 OpenAI-compatible、OpenRouter、Gemini、Anthropic Claude。

## CLI（本地目录 + CI 门禁）

```bash
git clone https://github.com/Snow7-G/SkillSeam && cd SkillSeam
echo '{"base_url": "https://.../v1", "api_key": "sk-...", "model": "..."}' > .atlasrc.json
python3 skill_seam.py ~/.agents/skills
open output/report.html
```

退出码：0 无冲突，1 有冲突，2 配置错了。接 CI 一行：

```bash
python3 skill_seam.py ./skills --tasks ci-tasks.json
```

## 真实问法比生成的有用

这是整个工具最要紧的一段，先说清楚。

SkillSeam 可以用 LLM 生成测试任务，但生成的任务有偏：出题的模型知道该哪个 skill 赢，所以题目偏简单。同一个 demo 上，生成的任务测出 0 个冲突，真实用户问法测出 4 个。同一批 skill，同一个模型。

所以工具内置了三种攒真实问法的方式：

```bash
# 装一次：之后你发给 Claude Code 的每条 prompt 都自动进问法库，静默零打扰
python3 skill_seam.py capture --install-claude

# 抓到 agent 选错技能的真实时刻，一条命令存成永久测试资产
python3 skill_seam.py mark "复诊的时候顺便查下会员积分" fuzhen-tixing

# 从问法库或 Codex 会话日志收割真实问法，LLM 预标应选技能，产出任务草稿
python3 skill_seam.py harvest ./skills --codex --label --out tasks-draft.json
```

草稿人工确认一遍再跑。攒十次真实事故，任务库比任何生成器都准。

生成的任务也没浪费，留着做冒烟测试。但绿了不代表没冲突，别信。

## 工作原理

1. 扫描 skill 目录，解析每个 SKILL.md 的 frontmatter，顺手做格式体检。
2. 组任务集：每个 skill 几条意图明确的正向任务，再加一批故意模糊的灰区任务（专门压在两个 skill 的边界上）。
3. 重演选择：模型只看 name 和 description，格式和 agent 真实注入时一样，给每条任务选一个技能。每条任务跑 5 次，temperature 0.7。
4. 多数投票汇总。5 次里至少 4 次一致地选错才算真冲突；不到这个数标记为不稳定，那是模型噪声，不是 bug，不污染报告。

报告是单文件 HTML，带混淆矩阵热力图。有冲突时还会生成 description 改写建议（改前/改后对照），改完重跑验证。

## 和现有工具的关系

| 工具 | 检查什么 | 粒度 |
|---|---|---|
| agnix | 格式规范（frontmatter、命名） | 单文件 |
| skilltest | 单个 skill 自己能不能触发 | 单 skill |
| SkillSpector（NVIDIA） | 安全（注入、外传、供应链） | 单 skill |
| **SkillSeam** | 组合之后的选择行为：谁抢谁的活 | 整个 skill 集合 |

互补关系。每个 skill 单独跑 lint 和安全扫描，整套放一起后跑 SkillSeam。

## 几句实话

模拟复现的是注入格式，没有驱动真实 agent 进程；跨运行时的行为差异（Codex 和 Claude 会不会选得不一样）在路线图上。Codex 会话解析是宽容抽取，工具输出可能混进收割候选，靠清洗规则缓解。网页界面目前是中文的。

## 名字的来历

冲突不住在 skill 内部，住在两个 skill 的接缝上。布料各自完好，衣服总在缝合处开线。SkillSeam 检查的就是这些接缝。

**关于重名。** 有一篇无关的论文与我们同名：《SkillSeam: Six Principles for Auditing Agent Skill Collections》（Kang Ruiyuan，X32 Studio，[arXiv:2609.13321](https://arxiv.org/abs/2609.13321)），2026 年 9 月发表，早于本项目。它用受控扰动审计技能集合，并附一个[可安装 skill](https://github.com/X32Studio/best-practice-for-skills-system)。本项目与之无关，也不是它的测量工具；名字取自「接缝」这个意象，当时并不知道该论文存在。如果你是顺着那篇论文找到这里的，这就是名字眼熟的原因。[两者的差异 →](research/protocol-alignment.md)


检测报告叫塞壬报告（Sirens Report），来自罗蕾莱。海涅写过：

> Ich weiß nicht, was soll es bedeuten,
> dass ich so traurig bin.

少女坐在莱茵河的礁石上梳头唱歌，船夫听见了歌，就看不见礁石了。

每一段 description 都在唱歌。有些歌，会把你的任务引上礁石。

## 开发

```bash
python3 tests/test_atlas.py   # 98 项测试，纯标准库
node tests/web_smoke.cjs      # 103 项网页断言，node >= 18
```

CI 覆盖 Python 3.10 / 3.12 / 3.13。提 PR 前看 CONTRIBUTING.md。MIT 许可证。
