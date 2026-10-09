# SkillSeam GitHub Action

把技能路由检查接进 CI：PR 修改了技能描述时自动运行 SkillSeam，
在合并前拦下「描述改坏导致的路由回归」和「描述抢任务」冲突。

```yaml
name: skill routing check
on:
  pull_request:
    paths: ["**/SKILL.md"]
jobs:
  skillseam:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: Snow7-G/SkillSeam/action@main
        with:
          skills-path: ./skills
          tasks-path: ./tests/skill-tasks.json
```

## 两种模式

### `detect`（默认）

对技能集做选择模拟，检测「谁抢了谁的活」。
无 API key 时可开 `mock: true` 做离线管线冒烟（结论不可信，仅验证流程）。

| 输入 | 必填 | 说明 |
|---|---|---|
| `skills-path` | ✅ | 技能集目录 |
| `tasks-path` | 可选 | 自定义任务清单 JSON（推荐真实用户问法；缺省自动生成） |
| `mock` | | 离线关键词打分，免密钥冒烟 |
| `fail-on-conflict` | | 发现冲突即失败（默认 true） |

### `compare`

用固定任务集验证描述改动：与基线对照，改进不会抵消回归。

| 输入 | 必填 | 说明 |
|---|---|---|
| `skills-path` | ✅ | 改动后的技能集 |
| `baseline-path` | ✅ | 改动前技能集（技能名须一致） |
| `tasks-path` | ✅ | 固定任务清单 JSON（经人工确认的标签） |
| `fail-on-regression` | | 出现回归即失败（默认 true） |
| `fail-on-unstable` | | 出现需人工复核的不稳定对即失败（默认 false） |

## 通用输入

| 输入 | 默认 | 说明 |
|---|---|---|
| `dashscope-api-key` / `deepseek-api-key` / `openai-api-key` | 对应环境变量 | 提供商密钥，从 secrets 传入 |
| `workers` | 8 | 并发请求数（被限流时调小） |
| `no-fixes` | true | 跳过 AI 修复建议（CI 推荐） |
| `python-version` | 3.12 | 运行时 Python 版本 |
| `report-artifact-name` | skillseam-report | 报告产物名（含 report.html / results.json） |

## 退出码 → CI 结果

| 退出码 | 含义 | detect | compare |
|---|---|---|---|
| 0 | 无冲突 / 无回归 | 通过 | 通过 |
| 1 | 冲突 / 回归 | 失败* | 失败* |
| 2 | 评测失败（密钥、输入） | 失败 | 失败 |
| 3 | 不稳定对需人工复核 | — | 默认通过 |

\* 由 `fail-on-conflict` / `fail-on-regression` 控制。

## 输出

| 输出 | 说明 |
|---|---|
| `exit-code` | skill-seam 原始退出码 |
| `verdict` | ok / conflict / regression / error / unstable |
| `report-dir` | 报告目录（report.html、results.json、comparison.json） |

报告同时写入 `$GITHUB_STEP_SUMMARY`，并以产物形式上传（`if-no-files-found: ignore`）。

## 注意事项

- 本仓库自带的 [action-selftest 工作流](../.github/workflows/action-selftest.yml)用 mock 模式做端到端自测（含「回归必须失败」的负路径断言）。
- `mock: true` 只验证管线连通性，**结论不可信**，不要作为合并依据。
- 真实模式的选型模拟会把技能描述与任务文本发送给你配置的模型提供商。
- 固定任务集请使用经人工确认标签的任务清单；自动生成的任务集只适合冒烟。
