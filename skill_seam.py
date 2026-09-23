#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SkillSeam (skill-seam) —— 模拟 agent 的 skill 选择过程，找出「谁抢了谁的活」。

用法:
    python skill_seam.py ./demo-skills                          # 自动生成任务 + 真实 LLM 模拟
    python skill_seam.py ./demo-skills --tasks my-tasks.json    # 用自己的任务清单
    python skill_seam.py ./demo-skills --demo-tasks             # 用内置 40 条眼科 demo 任务
    python skill_seam.py ./demo-skills --mock                   # 离线 mock（管线验证用）

任务来源优先级: --tasks > --demo-tasks > 自动生成（正向每 skill --gen-positive 条(默认5)，
灰区取 description 相似度最高的 --gray-pairs 对(默认2)，双向各 3 条）。生成结果落盘
output/tasks-generated.json 供人工审核后用 --tasks 复跑。

配置解析顺序: .atlasrc.json（当前目录或脚本目录）→ 环境变量（DASHSCOPE_API_KEY / OPENAI_API_KEY+OPENAI_BASE_URL）
事故库: skill-seam mark "任务" 应选技能名 —— 把真实事故标记进 ~/.skill-seam/marked.jsonl，
        检测时加 --with-marked 自动纳入（--list 查看）。
问法沉淀: skill-seam capture --install-claude 安装 Claude Code hook 被动收集 prompt；
        skill-seam harvest <skills目录> [--codex] [--label] 从问法库/会话日志收割任务草稿。
网页导出: skill-seam export <skills目录> 输出 "name: description" 行，直接粘进网页版。
输出: output/results.json + output/report.html；退出码 0=无冲突 1=有冲突 2=配置/运行错误
"""
import json
import os
import re
import sys
import time
import random
import shutil
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
import urllib.request
from sys import stderr as _stderr

__version__ = "0.1.0"

SAMPLES = 5          # 每任务采样次数
CONSISTENCY_MIN = 0.8  # 一致率低于此值标记为「不稳定」
MAX_WORKERS = 8

NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
STOPWORDS = {"相关", "处理", "包括", "以及", "问题", "使用", "进行", "通过", "对应", "完成", "说明", "解答", "受理"}


# ---------------------------------------------------------------- config
def load_config():
    cfg = None
    for p in (Path.cwd() / ".atlasrc.json", Path(__file__).parent / ".atlasrc.json"):
        if p.exists():
            try:
                cfg = json.loads(p.read_text(encoding="utf-8"))
            except json.JSONDecodeError as e:
                eprint(f"错误: {p} 不是合法 JSON: {e}")
                sys.exit(2)
            break
    if cfg is None:
        if os.environ.get("DASHSCOPE_API_KEY"):
            return {"mode": "real",
                    "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                    "api_key": os.environ["DASHSCOPE_API_KEY"],
                    "model": os.environ.get("ATLAS_MODEL", "qwen3.8-flash")}
        if os.environ.get("OPENAI_API_KEY"):
            return {"mode": "real",
                    "base_url": os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
                    "api_key": os.environ["OPENAI_API_KEY"],
                    "model": os.environ.get("ATLAS_MODEL", "gpt-4o-mini")}
        return None
    if not isinstance(cfg, dict):
        eprint("错误: .atlasrc.json 顶层必须是 JSON 对象")
        sys.exit(2)
    missing = [k for k in ("base_url", "api_key", "model")
               if not isinstance(cfg.get(k), str) or not cfg[k].strip()]
    if missing:
        eprint("错误: 模型配置缺少或存在无效字段: " + ", ".join(missing)
               + "（需要 base_url / api_key / model 三个字符串字段）")
        sys.exit(2)
    return cfg


# ---------------------------------------------------------------- scan (T2)


def _block_scalar(fm_lines, i, parent_indent):
    """解析 YAML 块标量（YAML 1.2.2 §6.5 折行规则 / §8.1.2 收尾规则）。

    fm_lines[i] 是头行（如 "description: >-"）。返回 (value, next_i, unsupported)。
    - 折叠(>)：相邻非空行折叠为空格；连续空行每个产生一个换行；
      更深缩进的行会破坏折行语义 → unsupported（调用方明确报错）。
    - 字面(|)：保留块内全部换行与额外缩进。
    - 收尾：clip(默认)保留一个末尾换行；strip(-)不保留；keep(+)保留全部。
    """
    header = fm_lines[i]
    ind_part = header.partition(":")[2].strip()
    style = ind_part[0]
    chomp = ind_part[1:]
    header_indent = len(header) - len(header.lstrip(" "))

    content = []          # (text, indent)；text 为 "" 表示真空行
    j = i + 1
    block_indent = None
    unsupported = False
    while j < len(fm_lines):
        line = fm_lines[j]
        if "\t" in line:
            unsupported = True  # Tab 在块标量中：声明不支持（Tab 不能用于缩进，字面保留场景过于边缘）
        if block_indent is not None and line.strip() == "" and len(line) > block_indent:
            # 超出块缩进的纯空白行：字面标量按原样保留；折叠标量按 more-indented 处理 → 不支持
            if style == ">":
                unsupported = True
            content.append((line[block_indent:], 0))
            j += 1
            continue
        if not line.strip():
            content.append(("", 0))
            j += 1
            continue
        indent = len(line) - len(line.lstrip(" "))
        if indent <= header_indent:
            break  # 缩进回退到键层级，块结束
        if block_indent is None:
            block_indent = indent
        if indent < block_indent:
            break  # 缩进小于块缩进，块结束
        text = line[block_indent:]
        if style == ">" and text.startswith((" ", "\t")):
            unsupported = True  # 折叠标量不支持更深缩进行（规范 §6.5 more-indented）
        content.append((text, indent))
        j += 1

    trailing_blanks = 0
    while content and content[-1][0] == "":
        content.pop()
        trailing_blanks += 1

    if style == "|":
        core = "\n".join(t for t, _ in content)
    else:
        out = []
        blanks = 0
        prev_break = False  # 上一行是内容行但两侧不折叠（更深缩进/纯空白超缩进行）
        for t, _ in content:
            if t == "":
                blanks += 1
                continue
            if t.strip() == "":
                # 纯空白超缩进行：作为内容行保留，两侧连接用换行
                if out:
                    out.append("\n" * max(blanks, 1))
                out.append(t)
                blanks = 0
                prev_break = True
                continue
            more = t.startswith((" ", "\t"))
            if more:
                unsupported = True
            if out:
                if blanks:
                    out.append("\n" * blanks)
                elif more or prev_more or prev_break:
                    out.append("\n")  # 更深缩进行两侧不折叠
                else:
                    out.append(" ")
            elif blanks:
                out.append("\n" * blanks)  # 开头空行按规范保留
            out.append(t)
            prev_more = more
            prev_break = False
            blanks = 0
        core = "".join(out)

    if chomp == "-":
        value = core
    elif chomp == "+":
        value = core + "\n" + "\n" * trailing_blanks if core else "\n" * trailing_blanks
    else:  # clip（默认）
        value = core + "\n" if core else ""
    return value, j, unsupported


def parse_frontmatter(text, path):
    issues = []
    text = text.replace("\r\n", "\n")  # CRLF 归一化，防止 name/description 尾部带 \r
    lines = text.split("\n")
    # 按原始行边界提取 frontmatter：不丢空行（keep 语义依赖它们）；
    # 闭合围栏必须在行首（列 0），块标量内容里的缩进 "---" 不是围栏
    if not lines or lines[0].rstrip() != "---":
        return None, ["缺少 frontmatter 或未闭合"]
    end = None
    for idx in range(1, len(lines)):
        if lines[idx].rstrip() == "---":
            end = idx
            break
    if end is None:
        return None, ["缺少 frontmatter 或未闭合"]
    fm = {}
    fm_lines = lines[1:end]
    body = "\n".join(lines[end + 1:]).strip()
    i = 0
    while i < len(fm_lines):
        line = fm_lines[i]
        if line.startswith("\t"):
            issues.append("[fatal] " + f"frontmatter 含 Tab 开头的行（YAML 不允许 Tab 缩进）: {line.strip()[:40]}")
            return None, issues
        if not line.strip():
            i += 1
            continue
        if ":" not in line:
            issues.append(f"frontmatter 存在无法解析的行（是否使用了不支持的多行语法？）: {line.strip()[:40]}")
            i += 1
            continue
        k, _, v = line.partition(":")
        k = k.strip()
        v = v.strip()
        if v and v[0] in (">", "|"):
            if v[1:] not in ("", "-", "+"):
                # 头行形态不支持（行内注释、显式缩进指示符等）→ 拒绝整个文件
                issues.append("[fatal] " + f"{k} 使用了暂不支持的块标量头 {v!r}"
                              + "（行内注释 / 显式缩进指示符）。请改用 >、>-、| 或 |-。")
                return None, issues
            # YAML 块标量（YAML 1.2.2 §8.1）：折行与收尾规则符合规范
            value, i_next, unsupported = _block_scalar(fm_lines, i, len(line) - len(line.lstrip(" ")))
            fm[k] = value
            if unsupported:
                issues.append("[fatal] " + f"{k} 折叠标量包含更深缩进的行，暂不支持（请改用 | 或统一缩进）")
            i = i_next
            continue
        fm[k] = v.strip('"').strip("'")
        i += 1
    name = fm.get("name", "")
    desc = fm.get("description", "")
    if not NAME_RE.match(name):
        issues.append(f"name 不符合规范: {name!r}")
    if name and path.parent.name != name:
        issues.append(f"name 与目录名不一致: {name} != {path.parent.name}")
    if not desc:
        issues.append("description 为空")
    elif len(desc) > 1024:
        issues.append(f"description 超长({len(desc)}>1024)")
    if not body:
        issues.append("正文为空")
    elif body.count("\n") > 500:
        issues.append("正文超过 500 行，应拆分到 references/")
    return {"name": name, "description": desc, "body_lines": body.count("\n") + 1}, issues


def scan_skills(root: Path):
    """返回 (skills, all_issues, rejected)。rejected 是含不可靠解析（[fatal]）的文件，
    调用方必须阻止评测而不是静默跳过。"""
    skills, all_issues, rejected = [], [], []
    for md in sorted(root.glob("*/SKILL.md")):
        skill, issues = parse_frontmatter(md.read_text(encoding="utf-8"), md)
        fatal = [i for i in issues if i.startswith("[fatal]")]
        if fatal:
            rejected.append((md, [i.replace("[fatal] ", "") for i in fatal]))
            continue
        if skill is None:
            all_issues.append((md, issues))
            continue
        skills.append(skill)
        if issues:
            all_issues.append((md, issues))
    return skills, all_issues, rejected


def build_catalog(skills):
    lines = []
    for i, s in enumerate(skills, 1):
        lines.append(f"{i}. name: {s['name']}")
        lines.append(f"   description: {s['description']}")
    return "\n".join(lines)


# ---------------------------------------------------------------- tasks (T3)
TASKS = [
    # ---- 正向：挂号预约 ----
    {"t": "我想预约下周三上午的眼科门诊。", "e": "guahao-yuyue", "kind": "positive"},
    {"t": "帮我取消明天的挂号，改约到周五。", "e": "guahao-yuyue", "kind": "positive"},
    {"t": "周六还有专家号吗？帮我挂一个。", "e": "guahao-yuyue", "kind": "positive"},
    {"t": "我预约错了时间，想改到下周二下午。", "e": "guahao-yuyue", "kind": "positive"},
    {"t": "帮我查一下我预约的就诊时间和地点。", "e": "guahao-yuyue", "kind": "positive"},
    # ---- 正向：报告解读 ----
    {"t": "我的 OCT 检查报告显示神经上皮层变薄，这严重吗？", "e": "baogao-jiedu", "kind": "positive"},
    {"t": "帮我解读一下眼压检查的数值。", "e": "baogao-jiedu", "kind": "positive"},
    {"t": "视野检查报告上有几个暗点是什么意思？", "e": "baogao-jiedu", "kind": "positive"},
    {"t": "验光单上的球镜柱镜数值是什么意思？", "e": "baogao-jiedu", "kind": "positive"},
    {"t": "医生说我的眼底照片有病变，帮我解释一下报告内容。", "e": "baogao-jiedu", "kind": "positive"},
    # ---- 正向：复诊提醒 ----
    {"t": "我做完白内障手术一个月了，该什么时候复查？", "e": "fuzhen-tixing", "kind": "positive"},
    {"t": "帮我安排下周的复诊时间。", "e": "fuzhen-tixing", "kind": "positive"},
    {"t": "复诊提醒能提前两天通知我吗？", "e": "fuzhen-tixing", "kind": "positive"},
    {"t": "我这次术后复查需要做哪些项目？", "e": "fuzhen-tixing", "kind": "positive"},
    {"t": "慢性青光眼多久需要复诊一次？", "e": "fuzhen-tixing", "kind": "positive"},
    # ---- 正向：术前须知 ----
    {"t": "后天做近视激光手术，术前有什么注意事项？", "e": "shuqian-xuzhi", "kind": "positive"},
    {"t": "白内障手术前需要禁食吗？禁食几小时？", "e": "shuqian-xuzhi", "kind": "positive"},
    {"t": "手术当天几点到院？需要带什么材料？", "e": "shuqian-xuzhi", "kind": "positive"},
    {"t": "术前可以戴隐形眼镜吗？", "e": "shuqian-xuzhi", "kind": "positive"},
    {"t": "做手术前需要停用哪些眼药水？", "e": "shuqian-xuzhi", "kind": "positive"},
    # ---- 正向：会员运营 ----
    {"t": "我的会员积分怎么兑换检查套餐？", "e": "huiyuan-yingxiao", "kind": "positive"},
    {"t": "黄金会员有什么专属权益？", "e": "huiyuan-yingxiao", "kind": "positive"},
    {"t": "帮我报名本月的会员免费眼底拍摄活动。", "e": "huiyuan-yingxiao", "kind": "positive"},
    {"t": "我的会员等级怎么升级？", "e": "huiyuan-yingxiao", "kind": "positive"},
    {"t": "积分有效期到什么时候？", "e": "huiyuan-yingxiao", "kind": "positive"},
    # ---- 正向：投诉受理 ----
    {"t": "我要投诉昨天就诊时护士的态度。", "e": "tousu-shouli", "kind": "positive"},
    {"t": "你们医院收费有问题，我要投诉。", "e": "tousu-shouli", "kind": "positive"},
    {"t": "投诉之后多久会有处理结果？", "e": "tousu-shouli", "kind": "positive"},
    {"t": "医生误诊了，我要正式投诉他。", "e": "tousu-shouli", "kind": "positive"},
    {"t": "投诉流程是怎么走的？需要准备什么？", "e": "tousu-shouli", "kind": "positive"},
    # ---- 灰区：挂号 vs 报告（撞车点1，预期归报告解读）----
    {"t": "我上周查的视力报告，你们能帮我看一下吗？", "e": "baogao-jiedu", "kind": "gray", "pair": "guahao↔baogao"},
    {"t": "把我的检查报告发我一下，顺便说说有什么问题。", "e": "baogao-jiedu", "kind": "gray", "pair": "guahao↔baogao"},
    {"t": "视力下降了，之前的报告还在吗？帮我查查。", "e": "baogao-jiedu", "kind": "gray", "pair": "guahao↔baogao"},
    {"t": "我想咨询一下报告里写的视网膜问题。", "e": "baogao-jiedu", "kind": "gray", "pair": "guahao↔baogao"},
    {"t": "报告咨询窗口怎么走？我要问一下报告结果。", "e": "baogao-jiedu", "kind": "gray", "pair": "guahao↔baogao"},
    # ---- 灰区：复诊 vs 会员（撞车点2）----
    {"t": "我术后复诊可以用会员积分抵扣吗？", "e": "fuzhen-tixing", "kind": "gray", "pair": "fuzhen↔huiyuan"},
    {"t": "会员的免费复查活动怎么预约？", "e": "huiyuan-yingxiao", "kind": "gray", "pair": "fuzhen↔huiyuan"},
    {"t": "复诊提醒可以发到我的会员小程序里吗？", "e": "fuzhen-tixing", "kind": "gray", "pair": "fuzhen↔huiyuan"},
    {"t": "我是黄金会员，复诊有折扣吗？", "e": "huiyuan-yingxiao", "kind": "gray", "pair": "fuzhen↔huiyuan"},
    {"t": "复诊的时候顺便帮我查下会员积分余额。", "e": "fuzhen-tixing", "kind": "gray", "pair": "fuzhen↔huiyuan"},
]


# ---------------------------------------------------------------- simulate (T4)
# 规则同步警告：本文件的 SYSTEM_PROMPT、CONSISTENCY_MIN(0.8)、冲突判定规则
# 与 docs/index.html（网页版）保持一致，任何一边修改必须同步另一边。
SYSTEM_PROMPT = (
    "你是客服 agent 的技能选择器。下面给出可用技能列表（仅名称与描述）。"
    "收到用户任务后，选出最合适的一个技能名称；若没有任何技能合适，输出 NONE。"
    '只输出 JSON：{"chosen": "<name|NONE>"}，不要输出其他内容。'
)


def chat_once(cfg, catalog, task_text):
    body = json.dumps({
        "model": cfg["model"],
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"可用技能：\n{catalog}\n\n用户任务：{task_text}"},
        ],
        "temperature": 0.7,
        "max_tokens": 60,
    }).encode("utf-8")
    req = urllib.request.Request(
        cfg["base_url"].rstrip("/") + "/chat/completions", data=body,
        headers={"Authorization": f"Bearer {cfg['api_key']}",
                 "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data["choices"][0]["message"]["content"]


def extract_chosen(content, valid_names):
    m = re.search(r'"chosen"\s*:\s*"([^"]+)"', content)
    if m:
        v = m.group(1).strip()
        if v == "NONE" or v in valid_names:
            return v
    s = content.strip()
    if s == "NONE" or s in valid_names:
        return s
    m2 = re.search(r"chosen['\"]?\s*[:=]\s*['\"]?([A-Za-z0-9-]+)", content)
    if m2 and (m2.group(1) == "NONE" or m2.group(1) in valid_names):
        return m2.group(1)
    return "INVALID"


def simulate_real(cfg, catalog, valid_names):
    jobs = [(ti, si) for ti in range(len(TASKS)) for si in range(SAMPLES)]
    results = {}
    done = [0]

    def work(job):
        ti, si = job
        for attempt in range(3):
            try:
                content = chat_once(cfg, catalog, TASKS[ti]["t"])
                return ti, si, extract_chosen(content, valid_names)
            except Exception:
                if attempt == 2:
                    return ti, si, "ERROR"
                time.sleep(1.5 * (attempt + 1))

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        for ti, si, chosen in ex.map(work, jobs):
            results[(ti, si)] = chosen
            done[0] += 1
            if done[0] % 40 == 0:
                print(f"  进度 {done[0]}/{len(jobs)}", flush=True)
    return results


def cjk_bigrams(s):
    s = re.sub(r"[^\u4e00-\u9fff a-z0-9]", " ", s.lower())
    toks = [t for t in s.split() if t]
    grams = set()
    for t in toks:
        if len(t) == 1:
            grams.add(t)
        for i in range(len(t) - 1):
            grams.add(t[i:i + 2])
    return grams


def simulate_mock(skills, valid_names):
    rng = random.Random(42)
    grams = {s["name"]: cjk_bigrams(s["description"]) for s in skills}
    results = {}
    for ti, task in enumerate(TASKS):
        tg = cjk_bigrams(task["t"])
        scores = {}
        for name in valid_names:
            base = len(tg & grams[name]) / max(len(grams[name]), 1)
            scores[name] = base
        for si in range(SAMPLES):
            noisy = {n: v * rng.uniform(0.85, 1.15) for n, v in scores.items()}
            best = max(noisy, key=noisy.get)
            results[(ti, si)] = best if noisy[best] > 0.04 else "NONE"
    return results


# ------------------------------------------------------- task generation (T11 前置)
def parse_json_loose(content):
    try:
        return json.loads(content)
    except Exception:
        m = re.search(r"\[.*\]|\{.*\}", content, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                return None
    return None


def desc_similarity(a, b):
    ga, gb = cjk_bigrams(a), cjk_bigrams(b)
    if not ga or not gb:
        return 0.0
    return 2 * len(ga & gb) / (len(ga) + len(gb))  # Dice 系数，避免短文本偏袒


def top_overlap_pairs(skills, k):
    scored = []
    for i in range(len(skills)):
        for j in range(i + 1, len(skills)):
            sim = desc_similarity(skills[i]["description"], skills[j]["description"])
            scored.append((sim, skills[i], skills[j]))
    scored.sort(key=lambda x: -x[0])
    return [(a, b) for sim, a, b in scored[:k] if sim > 0.05]


def llm_pick_pairs(cfg, skills, k):
    """让 LLM 判断哪些技能职责可能重叠（比词面相似度更接近语义，1 次调用）。失败返回 []。"""
    by_name = {s["name"]: s for s in skills}
    listing = "\n".join(f"- {s['name']}: {s['description']}" for s in skills)
    prompt = (f"以下是 {len(skills)} 个客服 agent 技能的名称与描述：\n{listing}\n\n"
              f"请找出职责最容易互相重叠、用户任务容易混淆的 {k} 对技能"
              f"（按混淆可能性从高到低）。"
              f'只输出 JSON：{{"pairs": [["技能名1", "技能名2"], ...]}}')
    try:
        obj = parse_json_loose(_gen_call(cfg, prompt))
        pairs, seen = [], set()
        for p in (obj or {}).get("pairs", []):
            if (isinstance(p, list) and len(p) == 2
                    and p[0] in by_name and p[1] in by_name and p[0] != p[1]):
                key = tuple(sorted((p[0], p[1])))
                if key in seen:
                    continue
                seen.add(key)
                pairs.append((by_name[p[0]], by_name[p[1]]))
        return pairs[:k]
    except Exception:
        return []


GEN_POS_PROMPT = (
    "根据技能的名称与描述，写 {n} 条真实用户可能提出的任务问法。"
    "要求：第一人称、口语化、句式多样、长短不一；不要出现技能名称本身；不要任何解释。"
    '只输出 JSON 数组：["任务1", "任务2", ...]'
)
GEN_GRAY_PROMPT = (
    "红队任务：下面两个技能的职责存在语义重叠。你的目标是写出最刁钻的用户问法——"
    "让 agent 极难判断该归 A 还是 B、甚至干脆选错的那种。"
    "问法要像真实用户的随意口吻：可以夹杂场景细节、模糊指代，两个技能的关键词各带一点。"
    "请写 {n} 组边界问法：每组两条，第一条正确答案应归技能A，第二条应归技能B，"
    "组内两条要高度相似以形成边界测试。"
    '只输出 JSON：{{"first": ["偏向A的问法"...], "second": ["偏向B的问法"...]}}'
)


def _gen_call(cfg, prompt):
    body = json.dumps({
        "model": cfg["model"],
        "messages": [{"role": "system", "content": "你是测试用例生成器，只输出 JSON。"},
                     {"role": "user", "content": prompt}],
        "temperature": 0.8,
        "max_tokens": 800,
    }).encode("utf-8")
    req = urllib.request.Request(
        cfg["base_url"].rstrip("/") + "/chat/completions", data=body,
        headers={"Authorization": f"Bearer {cfg['api_key']}",
                 "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=90) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data["choices"][0]["message"]["content"]


def generate_tasks_real(cfg, skills, n_pos, k_pairs, marked_examples=None):
    """LLM 自动生成：每 skill n_pos 条正向 + 灰区（LLM 挑重叠对，失败回退词面相似度）。

    marked_examples：真实问法样例（来自事故库/问法库），作为对抗生成的 few-shot，
    让模型模仿真实分布而非凭空想象。"""
    tasks, warnings = [], []
    all_names = [s["name"] for s in skills]
    seen_text = set()
    marked_examples = marked_examples or []

    pairs = llm_pick_pairs(cfg, skills, k_pairs)
    if pairs:
        print(f"  LLM 判定的重叠对: {'、'.join(a['name'] + '↔' + b['name'] for a, b in pairs)}")
    else:
        pairs = top_overlap_pairs(skills, k_pairs)
        print("  LLM 挑对失败，回退词面相似度筛选")
        warnings.append("灰区对由词面相似度筛选（LLM 挑对失败）")

    def gen_positive(s):
        prompt = (f"技能名称：{s['name']}\n技能描述：{s['description']}\n\n"
                  + GEN_POS_PROMPT.format(n=n_pos))
        for attempt in range(3):
            try:
                arr = parse_json_loose(_gen_call(cfg, prompt))
                if isinstance(arr, list):
                    # 泄题过滤：任务文本含任何技能名都会让选择器作弊；全局去重防一题两属
                    clean = []
                    for t in arr:
                        t = str(t).strip()
                        if not t or t in seen_text:
                            continue
                        if any(name in t for name in all_names):
                            continue
                        seen_text.add(t)
                        clean.append(t)
                    return [{"t": t, "e": s["name"], "kind": "positive"} for t in clean][:n_pos]
            except Exception:
                if attempt == 2:
                    break
                time.sleep(1.5)
        warnings.append(f"{s['name']} 正向任务生成失败，已跳过")
        return []

    def gen_gray(a, b):
        prompt = GEN_GRAY_PROMPT.format(n=3)
        body = (f"技能A：{a['name']}\n描述A：{a['description']}\n\n"
                f"技能B：{b['name']}\n描述B：{b['description']}")
        if marked_examples:
            samples = "\n".join(f"- {m}" for m in marked_examples[:3])
            body += (f"\n\n以下是真实用户问法的示例（模仿其语气与随意程度，"
                     f"不要照抄内容）：\n{samples}")

        def add(out, t, e, pair):
            t = str(t).strip()
            if not t or t in seen_text or any(name in t for name in all_names):
                return
            seen_text.add(t)
            out.append({"t": t, "e": e, "kind": "gray", "pair": pair})

        for attempt in range(3):
            try:
                obj = parse_json_loose(_gen_call(cfg, f"{body}\n\n{prompt}"))
                if isinstance(obj, dict):
                    pair = f"{a['name']}↔{b['name']}"
                    out = []
                    for t in (obj.get("first") or [])[:3]:
                        add(out, t, a["name"], pair)
                    for t in (obj.get("second") or [])[:3]:
                        add(out, t, b["name"], pair)
                    return out
            except Exception:
                if attempt == 2:
                    break
                time.sleep(1.5)
        warnings.append(f"{a['name']}↔{b['name']} 灰区任务生成失败，已跳过")
        return []

    with ThreadPoolExecutor(max_workers=4) as ex:
        pos_futs = [ex.submit(gen_positive, s) for s in skills]
        gray_futs = [ex.submit(gen_gray, a, b) for a, b in pairs]
        for fut in pos_futs:
            tasks.extend(fut.result())
        for fut in gray_futs:
            tasks.extend(fut.result())
    return tasks, warnings


def generate_tasks_mock(skills, n_pos, k_pairs):
    """mock 生成：模板拼接，任务与 description 同源（循环论证，仅验证管线，不可作结论）。"""
    tasks = []

    def label(s):
        m = re.match(r"[\u4e00-\u9fff]+", s["description"])
        return (m.group(0)[:8] if m else s["name"])

    for s in skills:
        for i in range(n_pos):
            tasks.append({"t": f"（样例{i + 1}）我想咨询一下{label(s)}相关的问题。",
                          "e": s["name"], "kind": "positive"})
    for a, b in top_overlap_pairs(skills, k_pairs):
        pair = f"{a['name']}↔{b['name']}"
        for i in range(3):
            tasks.append({"t": f"（灰区样例{i + 1}）关于{label(a)[:6]}的问题。",
                          "e": a["name"], "kind": "gray", "pair": pair})
            tasks.append({"t": f"（灰区样例{i + 1}）关于{label(b)[:6]}的问题。",
                          "e": b["name"], "kind": "gray", "pair": pair})
    return tasks


# ---------------------------------------------------------------- fix suggestions (T14)
FIX_PROMPT = (
    "你是 prompt 工程专家。技能 {thief} 的 description 截胡了本应属于技能 {victim} 的用户任务。\n\n"
    "技能 {victim}（应选）：\n{vdesc}\n\n技能 {thief}（实际被选中）：\n{tdesc}\n\n"
    "被截胡的任务：\n{tasks}\n\n"
    "请给出改写建议（1-2 条），通过修改其中一个或两个技能的 description 使边界清晰、截胡消失。"
    "优先改截胡方（加'仅限/不含'等边界词）。new_description 必须是完整可替换的 description，"
    "长度不超过 1024 字符，除边界外不得删减原职责。"
    '只输出 JSON：{{"changes": [{{"skill": "技能名", "new_description": "改写后的完整描述", '
    '"reason": "一句话理由"}}]}}'
)


def generate_fix_suggestions(cfg, rows, skills_by_name, max_pairs=5):
    """对每个稳定冲突对生成 description 改写建议。失败的对静默跳过。"""
    pairs = {}
    for r in rows:
        # 预期 NONE（过度接管）没有受害技能可改写 → 跳过建议生成，
        # 冲突本身仍在报告中并计入退出码
        if r["conflict"] and r["chosen"] in skills_by_name and r["expected"] in skills_by_name:
            pairs.setdefault((r["expected"], r["chosen"]), []).append(r)

    suggestions = []
    for (victim, thief), rs in list(pairs.items())[:max_pairs]:
        v, t = skills_by_name[victim], skills_by_name[thief]
        task_list = "\n".join(f"- {r['task']}" for r in rs[:5])
        prompt = FIX_PROMPT.format(thief=thief, victim=victim,
                                   vdesc=v["description"], tdesc=t["description"],
                                   tasks=task_list)
        for attempt in range(3):
            try:
                obj = parse_json_loose(_gen_call(cfg, prompt))
                if isinstance(obj, dict):
                    valid = []
                    for c in obj.get("changes", []):
                        if (isinstance(c, dict) and c.get("skill") in (victim, thief)
                                and c.get("new_description")
                                and len(str(c["new_description"])) <= 1024):
                            valid.append({"skill": c["skill"],
                                          "new_description": str(c["new_description"]).strip(),
                                          "reason": str(c.get("reason", "")).strip()})
                    if valid:
                        suggestions.append({"victim": victim, "thief": thief,
                                            "conflict_tasks": [r["task"] for r in rs[:3]],
                                            "changes": valid})
                        break
            except Exception:
                if attempt == 2:
                    break
                time.sleep(1.5)
    return suggestions


# ---------------------------------------------------------------- aggregate (T5)
def aggregate(votes_by_task, valid_names):
    rows = []
    for ti, task in enumerate(TASKS):
        votes = [votes_by_task[(ti, si)] for si in range(SAMPLES)]
        top, count = Counter(votes).most_common(1)[0]
        consistency = count / SAMPLES
        # INVALID 多数 = 模型输出持续不可解析，属工具侧失败而非 agent 行为，归为不稳定
        stable = consistency >= CONSISTENCY_MIN and top not in ("ERROR", "INVALID")
        conflict = bool(stable and top != task["e"])
        rows.append({"id": ti, "task": task["t"], "expected": task["e"],
                     "kind": task.get("kind", "positive"), "pair": task.get("pair", ""),
                     "votes": votes, "chosen": top, "consistency": consistency,
                     "stable": stable, "conflict": conflict})
    return rows


def _longest_hit(phrase, task, min_len=2):
    """phrase 与 task 的最长公共子串（≥min_len），用于解释截胡关键词。"""
    best = ""
    for i in range(len(phrase) - min_len + 1):
        for j in range(i + min_len, len(phrase) + 1):
            sub = phrase[i:j]
            if len(sub) > len(best) and sub in task:
                best = sub
    return best


def conflict_reason(row, skills_by_name):
    thief = skills_by_name.get(row["chosen"])
    if not thief:
        return []
    out = []
    for t in re.split(r"[，、。；：/（）\s]", thief["description"]):
        if len(t) < 2 or t in STOPWORDS:
            continue
        best = _longest_hit(t, row["task"])
        if best and best not in out:
            out.append(best)
    return out[:6]


# ---------------------------------------------------------------- report (T6)
CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, 'PingFang SC', 'Microsoft YaHei', sans-serif;
       background: #f5f4f0; color: #2c2c2a; padding: 32px 16px; }
.wrap { max-width: 900px; margin: 0 auto; }
h1 { font-size: 22px; font-weight: 500; margin-bottom: 4px; }
.sub { color: #5f5e5a; font-size: 13px; margin-bottom: 24px; }
.cards { display: flex; gap: 12px; flex-wrap: wrap; margin-bottom: 24px; }
.card { background: #fff; border: 0.5px solid #d3d1c7; border-radius: 12px; padding: 14px 18px; min-width: 130px; }
.card .num { font-size: 26px; font-weight: 500; }
.card .lbl { font-size: 12px; color: #5f5e5a; margin-top: 2px; }
.card.red .num { color: #a32d2d; }
.card.green .num { color: #3b6d11; }
section { background: #fff; border: 0.5px solid #d3d1c7; border-radius: 12px; padding: 20px; margin-bottom: 20px; }
h2 { font-size: 15px; font-weight: 500; margin-bottom: 12px; }
.conflict { border-left: 3px solid #e24b4a; padding: 10px 12px; background: #fcebeb;
            border-radius: 0 8px 8px 0; margin-bottom: 10px; font-size: 13px; line-height: 1.7; }
.conflict b.bad { color: #a32d2d; }
.badge { display: inline-block; background: #f7c1c1; color: #791f1f; border-radius: 4px;
         padding: 0 6px; font-size: 12px; margin: 0 2px; }
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th, td { text-align: left; padding: 6px 8px; border-bottom: 0.5px solid #e5e3dd; }
th { color: #5f5e5a; font-weight: 400; }
td.ok { color: #3b6d11; } td.bad { color: #a32d2d; } td.warn { color: #854f0b; }
details summary { cursor: pointer; font-size: 13px; color: #185fa5; }
.fix { border-left: 3px solid #3b6d11; padding: 10px 12px; background: #eaf3de;
       border-radius: 0 8px 8px 0; margin-bottom: 12px; font-size: 13px; line-height: 1.7; }
.fixhead { font-weight: 500; margin-bottom: 6px; }
.fixold { background: #fcebeb; border: 0.5px solid #f7c1c1; border-radius: 6px;
          padding: 6px 10px; margin: 4px 0; color: #791f1f; }
.fixnew { background: #fff; border: 0.5px solid #c0dd97; border-radius: 6px;
          padding: 6px 10px; margin: 4px 0; color: #27500a; }
.fixreason { color: #5f5e5a; font-size: 12px; margin-top: 4px; }
.note { font-size: 12px; color: #888780; margin-top: 16px; line-height: 1.6; }
"""


def esc(s):
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def render_report(rows, skills, meta):
    names = [s["name"] for s in skills]
    labels = {}
    for s in skills:
        cn = re.match(r"[\u4e00-\u9fff]+", s["description"])
        labels[s["name"]] = (cn.group(0)[:8] if cn else s["name"])
    cols = names + ["NONE", "其他"]
    idx = {n: i for i, n in enumerate(cols)}

    # 混淆矩阵: rows=expected（含 NONE 行，当存在预期 NONE 的任务）, cols=chosen
    row_names = names + (["NONE"] if any(r["expected"] == "NONE" for r in rows) else [])
    row_idx = {n: i for i, n in enumerate(row_names)}
    mat = [[0] * len(cols) for _ in row_names]
    for r in rows:
        if r["expected"] in idx and r["chosen"] in idx:
            mat[row_idx[r["expected"]]][idx[r["chosen"]]] += 1
        elif r["chosen"] not in idx:
            mat[row_idx[r["expected"]]][idx["其他"]] += 1

    cell_w, cell_h, lab_w, top_h = 86, 52, 168, 30
    W = lab_w + cell_w * len(cols) + 20
    H = top_h + cell_h * len(row_names) + 56
    svg = [f'<svg viewBox="0 0 {W} {H}" width="100%" xmlns="http://www.w3.org/2000/svg" role="img">',
           f'<text x="{lab_w}" y="14" font-size="12" fill="#5f5e5a">列 = agent 实际选中 →（行 = 应选技能）</text>']
    for ci, c in enumerate(cols):
        x = lab_w + ci * cell_w
        svg.append(f'<text x="{x + cell_w/2}" y="{top_h - 8}" font-size="11" fill="#444441" text-anchor="middle">{esc(c)}</text>')
    for ri, rn in enumerate(row_names):
        y = top_h + ri * cell_h
        svg.append(f'<text x="{lab_w - 8}" y="{y + cell_h/2}" font-size="11.5" fill="#444441" text-anchor="end">{esc(rn)}·{esc(labels.get(rn, "不应触发任何技能"))}</text>')
        for ci in range(len(cols)):
            x = lab_w + ci * cell_w
            v = mat[ri][ci]
            if ri == ci:
                fill = "#c0dd97" if v else "#f1efe8"
                tcol = "#27500a"
            elif c := (ci < len(names) and cols[ci] != "NONE"):
                fill = f"rgba(226,75,74,{min(0.12 + v * 0.16, 0.88):.2f})" if v else "#f1efe8"
                tcol = "#501313" if v else "#b4b2a9"
            else:
                fill = "#d3d1c7" if v else "#f1efe8"
                tcol = "#444441"
            svg.append(f'<rect x="{x}" y="{y}" width="{cell_w-4}" height="{cell_h-4}" rx="6" fill="{fill}" stroke="#b4b2a9" stroke-width="0.5"/>')
            if v:
                svg.append(f'<text x="{x + (cell_w-4)/2}" y="{y + (cell_h-4)/2 + 4}" font-size="13" fill="{tcol}" text-anchor="middle">{v}</text>')
    svg.append("</svg>")
    matrix_svg = "\n".join(svg)

    conflicts = [r for r in rows if r["conflict"]]
    unstable = [r for r in rows if not r["stable"] and not r["conflict"]]
    hits = sum(1 for r in rows if r["chosen"] == r["expected"])
    conf_html = ""
    for r in conflicts:
        terms = conflict_reason(r, {s["name"]: s for s in skills})
        badges = "".join(f'<span class="badge">{esc(t)}</span>' for t in terms)
        kind = {"gray": "灰区", "marked": "事故"}.get(r["kind"], "正向")
        if r["chosen"] == "NONE":
            act = '没有任何技能接住（agent 选择 NONE）'
        elif r["chosen"] == "ERROR":
            act = '模拟调用失败'
        else:
            act = f'实际被 <b class="bad">{r["chosen"]}</b> 截胡'
        conf_html += (
            f'<div class="conflict">[{kind}{("·" + r["pair"]) if r["pair"] else ""}] '
            f'「{esc(r["task"])}」<br>'
            f'应选 <b>{r["expected"]}</b>，{act}'
            f'（{int(r["consistency"] * SAMPLES)}/{SAMPLES} 票，一致率 {r["consistency"]:.0%}）'
            + (f'<br>截胡关键词：{badges}' if badges else "")
            + "</div>")
    if not conf_html:
        conf_html = '<div class="conflict" style="border-color:#3b6d11;background:#eaf3de">未发现稳定冲突。</div>'

    fixes = meta.get("fix_suggestions") or []
    fix_html = ""
    for s in fixes:
        for c in s["changes"]:
            old_desc = next((sk["description"] for sk in skills if sk["name"] == c["skill"]), "")
            fix_html += (
                f'<div class="fix"><div class="fixhead">修改 {esc(c["skill"])}'
                f'<span class="fixreason">（冲突：{esc(s["victim"])} 被 {esc(s["thief"])} 截胡）</span></div>'
                f'<div class="fixold"><b>改前</b>：{esc(old_desc)}</div>'
                f'<div class="fixnew"><b>改后</b>：{esc(c["new_description"])}</div>'
                f'<div class="fixreason">理由：{esc(c["reason"])}</div></div>')
    if conflicts and not fix_html:
        fix_html = ('<div class="note">未能自动生成建议。可按冲突明细中的截胡关键词手动修改 description：'
                    '给截胡方加"仅限/不含"边界词，把越界职责让给应选技能。</div>')
    fix_section = ""
    if conflicts:
        fix_section = f"<section><h2>修复建议（AI 生成，改后请重跑验证）</h2>{fix_html}</section>"

    trs = ""
    for r in rows:
        cls = "ok" if r["chosen"] == r["expected"] else ("bad" if r["conflict"] else "warn")
        flag = "命中" if r["chosen"] == r["expected"] else ("✗ 截胡" if r["conflict"] else "~ 不稳定")
        trs += (f'<tr><td>{esc(r["task"])}</td><td>{r["expected"]}</td>'
                f'<td class="{cls}">{esc(r["chosen"])}</td>'
                f'<td class="{cls}">{flag}（{int(r["consistency"] * SAMPLES)}/{SAMPLES}）</td></tr>')

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    html = f"""<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>SkillSeam · Sirens Report</title><style>{CSS}</style></head><body><div class="wrap">
<h1>SkillSeam · Sirens Report</h1>
<div class="sub">{esc(meta['mode_label'])} · 模型 {esc(meta['model'])} · {len(rows)} 任务 × {SAMPLES} 采样 · {now}</div>
<div class="cards">
<div class="card green"><div class="num">{hits}/{len(rows)}</div><div class="lbl">任务命中预期技能</div></div>
<div class="card red"><div class="num">{len(conflicts)}</div><div class="lbl">稳定冲突（截胡）</div></div>
<div class="card"><div class="num">{len(unstable)}</div><div class="lbl">不稳定（未达一致率）</div></div>
<div class="card"><div class="num">{len(names)}</div><div class="lbl">参与技能数</div></div>
</div>
<section><h2>选择混淆矩阵</h2>{matrix_svg}
<div class="note">对角线 = 应选技能被正确选中；红色 = 被其他技能截胡，颜色越深次数越多。</div></section>
<section><h2>冲突明细</h2>{conf_html}</section>
{fix_section}
<section><details><summary>全部 {len(rows)} 条任务的模拟明细</summary>
<table><tr><th>任务</th><th>应选</th><th>实际选中</th><th>结果</th></tr>{trs}</table></details></section>
<div class="note">SkillSeam · 仅注入 name+description 模拟 agent 技能选择 · 退出码 {"1(有冲突)" if conflicts else "0(无冲突)"}</div>
</div></body></html>"""
    return html


# ---------------------------------------------------------------- 事故库（方案二）
def marked_library_path(argv):
    if "--library" in argv and argv.index("--library") + 1 < len(argv):
        return Path(argv[argv.index("--library") + 1])
    return Path.home() / ".skill-seam" / "marked.jsonl"


def load_marked(lib: Path):
    entries = []
    if not lib.exists():
        return entries
    for line in lib.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and obj.get("t") and obj.get("e"):
            entries.append({"t": str(obj["t"]), "e": str(obj["e"]), "kind": "marked",
                            "ts": str(obj.get("ts", ""))})
    return entries


def cmd_mark(argv):
    """skill-seam mark [--list] [--library PATH] "任务文本" 应选技能名"""
    lib = marked_library_path(argv)
    if "--list" in argv:
        entries = load_marked(lib)
        if not entries:
            print(f"事故库为空（{lib}）")
            return 0
        print(f"事故库 {lib}，共 {len(entries)} 条：")
        for i, e in enumerate(entries):
            print(f"  [{i}] {e['t'][:40]}  =>  {e['e']}")
        return 0
    positional = []
    for i, a in enumerate(argv):
        if a == "--library":
            continue
        if i > 0 and argv[i - 1] == "--library":
            continue
        if a.startswith("--"):
            continue
        positional.append(a)
    if len(positional) != 2:
        print('用法: skill-seam mark "任务文本" 应选技能名 [--library 路径] [--list]')
        return 2
    text, expected = positional[0].strip(), positional[1].strip()
    if not text:
        eprint("错误: 任务文本为空")
        return 2
    if not NAME_RE.match(expected):
        eprint(f"错误: 应选技能名不符合规范（小写字母/数字/连字符）: {expected}")
        return 2
    existing = load_marked(lib)
    for e in existing:
        if e["t"] == text and e["e"] == expected:
            print(f"已存在（#{existing.index(e)}），无需重复标记。当前事故库共 {len(existing)} 条。")
            return 0
    lib.parent.mkdir(parents=True, exist_ok=True)
    with lib.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": datetime.now().isoformat(timespec="seconds"),
                            "t": text, "e": expected}, ensure_ascii=False) + "\n")
    print(f"已标记事故 → {lib}（当前共 {len(existing) + 1} 条）。"
          f"运行检测时加 --with-marked 即可把事故纳入任务集。")
    return 0


# ---------------------------------------------------------------- 问法捕获（方案一）
def queries_path(argv):
    if "--queries" in argv and argv.index("--queries") + 1 < len(argv):
        return Path(argv[argv.index("--queries") + 1])
    return Path.home() / ".skill-seam" / "queries.jsonl"


def cmd_capture(argv):
    """skill-seam capture [--queries PATH] [--install-claude [--settings PATH]]

    无参数模式：从 stdin 读一条用户 prompt（Claude Code hook 传入的 JSON 或纯文本），
    追加到本地问法库。任何异常都不抛出——捕获永远不能打断用户会话。
    """
    try:
        lib = queries_path(argv)
        if "--install-claude" in argv:
            return install_claude_hook(argv)
        if sys.stdin.isatty():
            # 交互式终端直跑会挂起等 EOF——捕获只能由 hook 管道调用
            print("capture 从 stdin 读取 prompt（由 Claude Code hook 调用，不用于交互）。\n"
                  "安装被动捕获: capture --install-claude")
            return 0
        raw = sys.stdin.read()
        text = ""
        try:
            obj = json.loads(raw)
            if isinstance(obj, dict):
                text = str(obj.get("prompt") or obj.get("text") or "")
        except Exception:
            text = raw
        text = text.strip()
        if text:
            lib.parent.mkdir(parents=True, exist_ok=True)
            with lib.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"ts": datetime.now().isoformat(timespec="seconds"),
                                    "text": text}, ensure_ascii=False) + "\n")
    except Exception:
        pass  # 捕获失败必须静默，绝不影响宿主会话
    return 0


def install_claude_hook(argv):
    """把 capture 命令作为 UserPromptSubmit hook 合并进 Claude Code settings.json。"""
    settings = Path.home() / ".claude" / "settings.json"
    if "--settings" in argv and argv.index("--settings") + 1 < len(argv):
        settings = Path(argv[argv.index("--settings") + 1])
    cmd = f'{sys.executable} {Path(__file__).resolve()} capture'
    data = {}
    if settings.exists():
        data = json.loads(settings.read_text(encoding="utf-8"))
    hooks = data.setdefault("hooks", {})
    ups = hooks.setdefault("UserPromptSubmit", [])
    already = any("skill_seam.py capture" in h.get("command", "")
                  for entry in ups for h in entry.get("hooks", []))
    if already:
        print("Claude Code hook 已安装过，无需重复。")
        return 0
    ups.append({"hooks": [{"type": "command", "command": cmd}]})
    if settings.exists():
        backup = settings.with_name(settings.name + ".bak-" +
                                    datetime.now().strftime("%Y%m%d%H%M%S"))
        shutil.copy2(settings, backup)
        print(f"已备份原配置 → {backup}")
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"已安装 Claude Code hook → {settings}")
    print(f"之后每次提交的 prompt 都会自动记录到问法库，用 harvest 命令收割。")
    return 0


def _walk_user_text(node, out):
    """从 Codex 会话 JSON 的任意嵌套结构里抽 user 消息文本（宽容解析）。"""
    if isinstance(node, dict):
        if node.get("role") == "user":
            c = node.get("content")
            if isinstance(c, list):
                for item in c:
                    if isinstance(item, dict) and isinstance(item.get("text"), str):
                        out.append(item["text"])
            elif isinstance(c, str):
                out.append(c)
        for v in node.values():
            _walk_user_text(v, out)
    elif isinstance(node, list):
        for v in node:
            _walk_user_text(v, out)


def collect_codex_queries(codex_dir: Path):
    queries = []
    if not codex_dir.exists():
        return queries
    for f in codex_dir.rglob("*.jsonl"):
        for line in f.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            _walk_user_text(obj, queries)
    return queries


def cmd_harvest(argv):
    """skill-seam harvest <skills目录> [--claude] [--codex] [--label]
            [--out FILE] [--limit N] [--min-len N] [--queries PATH] [--codex-dir PATH]

    从本地问法库/会话日志收割真实用户问法，过滤去重后产出任务草稿（tasks-draft）。
    --label 用 LLM 给每条问法预标应选技能（草稿性质，仍需人工确认）。
    """
    paths = [a for a in argv if not a.startswith("--")]
    if not paths:
        eprint("用法: skill-seam harvest <skills目录> [--claude] [--codex] [--label] [--out FILE]")
        return 2
    root = Path(paths[0])
    skills, _, rejected = scan_skills(root)
    if rejected:
        eprint("错误: 存在无法可靠解析的 SKILL.md，收割中止。")
        for md, msgs in rejected:
            for msg in msgs:
                eprint(f"  {md}: {msg}")
        return 2
    if len(skills) < 1:
        eprint(f"错误: {root} 下没有 SKILL.md")
        return 2

    def opt(flag, default):
        if flag in argv and argv.index(flag) + 1 < len(argv):
            return argv[argv.index(flag) + 1]
        return default

    limit = max(1, int(opt("--limit", "60")))
    min_len = max(2, int(opt("--min-len", "6")))
    out = Path(opt("--out", "tasks-draft.json"))

    raw = []
    sources = []
    use_claude = "--claude" in argv or ("--codex" not in argv and queries_path(argv).exists())
    use_codex = "--codex" in argv
    if use_claude:
        qlib = queries_path(argv)
        for line in (qlib.read_text(encoding="utf-8").splitlines() if qlib.exists() else []):
            try:
                obj = json.loads(line)
                raw.append(str(obj.get("text", "")))
            except json.JSONDecodeError:
                continue
        if qlib.exists():
            sources.append(f"问法库({qlib})")
    if use_codex:
        codex_dir = Path(opt("--codex-dir", str(Path.home() / ".codex" / "sessions")))
        found = collect_codex_queries(codex_dir)
        raw.extend(found)
        sources.append(f"Codex 会话({codex_dir}，{len(found)} 条原始记录)")
    if not raw:
        print("没有可收割的问法。两个入口：")
        print("  1) capture --install-claude 安装 Claude Code hook，用着用着就积累")
        print("  2) harvest --codex 直接解析 Codex 会话日志")
        return 2

    # 清洗：去重、过滤斜杠命令、过短与明显非任务的输入
    seen, cleaned = set(), []
    for q in raw:
        q = q.strip()
        if len(q) < min_len or q.startswith("/") or q in seen:
            continue
        seen.add(q)
        cleaned.append(q)

    # 相关性排序：与最相似技能 description 的 Dice 系数
    def max_sim(text):
        tg = cjk_bigrams(text)
        return max((len(tg & cjk_bigrams(s["description"])) /
                    max(len(tg) + len(cjk_bigrams(s["description"])) - len(tg & cjk_bigrams(s["description"])), 1)
                    for s in skills), default=0.0)
    scored = sorted(((max_sim(q), q) for q in cleaned), key=lambda x: -x[0])
    drafts = [q for sim, q in scored if sim > 0.02][:limit]
    if not drafts:
        drafts = [q for _, q in scored[:limit]]
    print(f"来源: {'、'.join(sources) or '无'} | 原始 {len(raw)} 条 → 清洗后 {len(cleaned)} 条 → 产出草稿 {len(drafts)} 条")

    # 可选：LLM 预标应选技能（草稿性质，结果仍需人工确认）
    hint_map = {}
    if "--label" in argv:
        cfg = load_config()
        if cfg:
            catalog = build_catalog(skills)
            names = [s["name"] for s in skills]
            print("LLM 预标中（结果仅作草稿，需人工确认）...")
            for q in drafts:
                try:
                    hint = extract_chosen(chat_once(cfg, catalog, q), names)
                except Exception:
                    hint = "INVALID"
                if hint not in ("NONE", "INVALID", "ERROR"):
                    hint_map[q] = hint
            print(f"  预标 {len(hint_map)}/{len(drafts)} 条")
        else:
            print("[warn] 未配置 provider，跳过 --label")

    payload = [{"t": q, "e": hint_map.get(q, ""), "hint": q in hint_map} for q in drafts]
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"任务草稿 → {out}")
    print("下一步：为每条草稿补 \"e\"（应选技能）字段——看着自己说过的话做判断，通常很快；")
    print("补完即可 --tasks 使用。带 => 标注的灰区问法价值最高。")
    for q in drafts[:10]:
        print(f"  · {q[:48]}")
    return 0


def cmd_export(argv):
    """skill-seam export <skills目录> —— 输出网页版可直接粘贴的 "name: description" 行。"""
    paths = [a for a in argv if not a.startswith("--")]
    root = Path(paths[0]) if paths else Path("./demo-skills")
    skills, _, rejected = scan_skills(root)
    if rejected:
        eprint("错误: 以下 SKILL.md 存在无法可靠解析的语法，export 拒绝输出：")
        for md, msgs in rejected:
            for msg in msgs:
                eprint(f"  {md}: {msg}")
        return 2
    if not skills:
        eprint(f"错误: {root} 下没有 SKILL.md")
        return 2
    for s in skills:
        print(f"{s['name']}: {s['description']}")
    return 0


# ---------------------------------------------------------------- main
HELP_TEXT = """SkillSeam {version} —— 模拟 agent 的 skill 选择过程，找出「谁抢了谁的活」

用法:
  skill-seam <skills目录> [选项]        检测（默认自动生成任务）
  skill-seam mark "任务" 应选技能名     把真实事故标记进本地事故库
  skill-seam capture --install-claude   安装 Claude Code hook 被动收集 prompt
  skill-seam harvest <skills目录>       从问法库/会话日志收割任务草稿
  skill-seam export <skills目录>        输出网页版粘贴格式（name: description）

检测选项:
  --tasks <file.json>    自定义任务清单（推荐：真实用户问法）
  --demo-tasks           内置 40 条眼科 demo 任务
  --gen-positive <N>     自动生成时每技能正向任务数（默认 5）
  --gray-pairs <K>       自动生成时灰区技能对数（默认 2，0=不生成）
  --with-marked          合并事故库中适用于当前技能集的条目
  --out <目录>           报告输出目录（默认当前目录下 output/）
  --mock                 离线关键词打分模式（仅验证管线，结论不可信）
  -h, --help             显示本帮助
  -V, --version          显示版本

配置: .atlasrc.json（当前目录或脚本目录）→ 环境变量 DASHSCOPE_API_KEY / OPENAI_API_KEY
退出码: 0 无冲突 · 1 有冲突 · 2 配置、参数或评测失败（无有效采样）
文档: https://github.com/Snow7-G/SkillSeam"""


def eprint(*a):
    print(*a, file=sys.stderr)


def main():
    args = sys.argv[1:]
    if "--version" in args or "-V" in args:
        print(f"SkillSeam {__version__}")
        return 0
    if args and args[0] in ("-h", "--help", "help"):
        print(HELP_TEXT.replace("{version}", __version__))
        return 0
    if args and args[0] == "mark":
        sys.exit(cmd_mark(args[1:]))
    if args and args[0] == "capture":
        sys.exit(cmd_capture(args[1:]))
    if args and args[0] == "harvest":
        sys.exit(cmd_harvest(args[1:]))
    if args and args[0] == "export":
        sys.exit(cmd_export(args[1:]))
    mock = "--mock" in args
    task_file = None
    if "--tasks" in args:
        ti = args.index("--tasks")
        if ti + 1 >= len(args):
            eprint("错误: --tasks 需要一个 JSON 文件路径")
            sys.exit(2)
        task_file = Path(args[ti + 1])
        if not task_file.exists():
            eprint(f"错误: 任务文件不存在: {task_file}")
            sys.exit(2)
    skip = {"--mock", "--demo-tasks", "--with-marked", "--tasks",
            str(task_file) if task_file else None,
            "--gen-positive", "--gray-pairs"}
    if "--out" in args:
        skip.add("--out")
        oi = args.index("--out")
        if oi + 1 < len(args):
            skip.add(args[oi + 1])
    # 数值型旗标的值也不算位置参数
    for flag in ("--gen-positive", "--gray-pairs"):
        if flag in args and args.index(flag) + 1 < len(args):
            skip.add(args[args.index(flag) + 1])
    paths = [a for a in args if a not in skip]
    root = Path(paths[0]) if paths else Path("./demo-skills")
    if not root.exists():
        eprint(f"错误: skill 目录不存在: {root}")
        sys.exit(2)

    def int_opt(flag, default, minimum=1):
        if flag in args and args.index(flag) + 1 < len(args):
            try:
                return max(minimum, int(args[args.index(flag) + 1]))
            except ValueError:
                eprint(f"错误: {flag} 需要一个整数")
                sys.exit(2)
        return default

    n_pos = int_opt("--gen-positive", 5)
    k_pairs = int_opt("--gray-pairs", 2, minimum=0)  # 0 = 不生成灰区任务

    skills, issues, rejected = scan_skills(root)
    if rejected:
        for md, msgs in rejected:
            for msg in msgs:
                eprint(f"错误: {md}: {msg}")
        eprint("错误: 存在无法可靠解析的 SKILL.md，评测中止（拒绝返回 0）。")
        sys.exit(2)
    if not skills:
        eprint("错误: 未找到任何 SKILL.md")
        sys.exit(2)
    for p, iss in issues:
        print(f"[warn] {p}: {'; '.join(iss)}")
    valid_names = [s["name"] for s in skills]

    out = Path.cwd() / "output"
    if "--out" in args and args.index("--out") + 1 < len(args):
        out = Path(args[args.index("--out") + 1])
    out.mkdir(exist_ok=True)
    task_source = "user"
    if task_file:
        try:
            loaded = json.loads(task_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            eprint(f"错误: 任务文件不是合法 JSON: {e}")
            sys.exit(2)
        if not isinstance(loaded, list):
            eprint("错误: 任务文件必须是 JSON 数组（元素含 t/e/kind/pair 字段）")
            sys.exit(2)
        bad = []
        for idx, item in enumerate(loaded):
            if not isinstance(item, dict):
                bad.append(f"第 {idx + 1} 条不是 JSON 对象")
                continue
            t, e = item.get("t"), item.get("e")
            if not isinstance(t, str) or not t.strip():
                bad.append(f"第 {idx + 1} 条的 t(任务文本) 必须是非空字符串")
            elif not isinstance(e, str) or not e.strip():
                bad.append(f"第 {idx + 1} 条的 e(应选技能) 必须是非空字符串（\'NONE\' 表示不应触发任何技能）")
        if bad:
            eprint(f"错误: 任务文件存在 {len(bad)} 条无效条目: " + "; ".join(bad[:5]))
            sys.exit(2)
        TASKS.clear()
        TASKS.extend(loaded)
    elif "--demo-tasks" in args:
        task_source = "内置 demo"
    else:
        # 默认：自动生成任务（正向逐 skill + 灰区取相似度最高的 k 对）
        cfg0 = None if mock else load_config()
        if mock or cfg0 is None:
            gen = generate_tasks_mock(skills, n_pos, k_pairs)
            task_source = "auto(mock，仅验证管线)"
        else:
            print(f"自动生成任务中（正向 {n_pos}/skill，灰区取相似度前 {k_pairs} 对）...")
            gen, warns = generate_tasks_real(
                cfg0, skills, n_pos, k_pairs,
                marked_examples=[m["t"] for m in load_marked(marked_library_path(args))[:3]])
            task_source = "auto(LLM)"
            for w in warns:
                print(f"[warn] {w}")
        if not gen:
            eprint("错误: 任务生成结果为空，无法继续")
            sys.exit(2)
        TASKS.clear()
        TASKS.extend(gen)
        (out / "tasks-generated.json").write_text(
            json.dumps(gen, ensure_ascii=False, indent=2), encoding="utf-8")

    # 事故库合并（--with-marked）：只纳入应选技能存在于当前集合的条目
    if "--with-marked" in args:
        lib = marked_library_path(args)
        marked = load_marked(lib)
        existing_texts = {t["t"] for t in TASKS}
        applicable, skipped = [], 0
        for m in marked:
            if m["e"] not in valid_names:
                skipped += 1
                continue
            if m["t"] in existing_texts:
                continue
            existing_texts.add(m["t"])
            applicable.append(m)
        TASKS.extend(applicable)
        if applicable or skipped:
            print(f"事故库合并: 纳入 {len(applicable)} 条"
                  + (f"（跳过 {skipped} 条：应选技能不在当前集合）" if skipped else ""))
        if "--with-marked" in args and applicable:
            task_source = f"{task_source} + 事故库"
    else:
        lib = None

    unknown = sorted({t["e"] for t in TASKS if t["e"] != "NONE"} - set(valid_names))
    if unknown:
        eprint(f"错误: 任务清单中的应选技能不存在于 skill 目录: {unknown}")
        sys.exit(2)
    catalog = build_catalog(skills)
    print(f"扫描到 {len(skills)} 个 skill；任务来源: {task_source}，共 {len(TASKS)} 条 × {SAMPLES} 采样 = {len(TASKS) * SAMPLES} 次选择")

    cfg = None if mock else load_config()
    if cfg is None and not mock:
        eprint("错误: 未检测到模型配置（.atlasrc.json 或环境变量 DASHSCOPE_API_KEY / OPENAI_API_KEY）。")
        eprint("       若只想离线验证管线，请显式加 --mock。")
        sys.exit(2)
    if mock:
        t0 = time.time()
        votes = simulate_mock(skills, valid_names)
        mode_label, model = "MOCK 模式（离线关键词打分，非真实模型）", "keyword-mock"
    else:
        print(f"provider: {cfg['base_url']}  model: {cfg['model']}")
        t0 = time.time()
        votes = simulate_real(cfg, catalog, valid_names)
        mode_label, model = "真实 LLM 模拟", cfg["model"]
    print(f"模拟完成，耗时 {time.time() - t0:.1f}s")

    rows = aggregate(votes, valid_names)
    conflicts = [r for r in rows if r["conflict"]]

    fix_suggestions = []
    if conflicts and not (mock or cfg is None):
        print(f"为 {len(conflicts)} 个冲突生成修复建议...")
        fix_suggestions = generate_fix_suggestions(cfg, rows, {s["name"]: s for s in skills})
        print(f"  生成 {len(fix_suggestions)} 组建议")
    elif conflicts:
        print("（mock 模式跳过修复建议生成）")

    meta = {"mode_label": mode_label, "model": model, "samples": SAMPLES,
            "consistency_min": CONSISTENCY_MIN, "skills": skills, "task_source": task_source,
            "fix_suggestions": fix_suggestions,
            "generated_at": datetime.now().isoformat()}
    (out / "results.json").write_text(
        json.dumps({"meta": meta, "tasks": [{"text": t["t"], "expected": t["e"], "kind": t.get("kind", "positive")} for t in TASKS],
                    "rows": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "report.html").write_text(render_report(rows, skills, meta), encoding="utf-8")

    print(f"\n===== 摘要 =====")
    hits = sum(1 for r in rows if r["chosen"] == r["expected"])
    print(f"命中 {hits}/{len(rows)}  稳定冲突 {len(conflicts)}  不稳定 {sum(1 for r in rows if not r['stable'] and not r['conflict'])}")
    for r in conflicts:
        print(f"  [截胡] 「{r['task'][:28]}…」应选 {r['expected']} → 实际 {r['chosen']} ({int(r['consistency'] * SAMPLES)}/{SAMPLES})")
    print(f"\n报告: {out / 'report.html'}")
    if not any(v in valid_names or v == "NONE" for v in votes.values()):
        eprint("错误: 评测失败，无有效采样（请求失败或响应不可解析）；不能判定为无冲突。")
        sys.exit(2)
    sys.exit(1 if conflicts else 0)


if __name__ == "__main__":
    main()
