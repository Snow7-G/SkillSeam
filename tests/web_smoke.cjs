// SkillSeam web smoke test（node >= 18，无依赖；CI 与本地共用）
// 运行: node tests/web_smoke.cjs
const fs = require("fs");
const path = require("path");

const els = {};
global.document = { getElementById: (id) => {
    if (!els[id]) els[id] = { addEventListener() {}, value: "", checked: true, style: {},
      classList: { toggle() {}, remove() {}, add() {}, contains: () => false },
      innerHTML: "", textContent: "", placeholder: "", checked: true,
      disabled: false, scrollIntoView() {},
      getAttribute: () => null, setAttribute: () => {}, querySelectorAll: () => [] };
    return els[id];
  }, querySelectorAll: () => [], documentElement: { lang: "" } };
const store = {};
const removedKeys = [];
global.localStorage = {
  getItem: (k) => (k in store ? store[k] : null),
  setItem: (k, v) => { store[k] = String(v); },
  removeItem: (k) => { removedKeys.push(k); delete store[k]; },
};
global.fetch = () => Promise.reject(new Error("no network"));
global.window = { addEventListener: () => {} };  // 页面在 DOMContentLoaded 里绑定文件夹选择
// Node 21+ 自带只读的 navigator 全局对象，直接赋值会静默失效，必须用 defineProperty
Object.defineProperty(global, "navigator", {
  value: { language: "zh-CN" }, writable: true, configurable: true });
global.location = { search: "", href: "http://localhost/" };
global.history = { replaceState: () => {} };

const html = fs.readFileSync(path.join(__dirname, "..", "docs", "index.html"), "utf-8");
const m = html.match(/<script>([\s\S]*)<\/script>/);
if (!m) { console.error("FAIL: 未找到 <script> 块"); process.exit(1); }
// 提取 JS 中的数据与函数，去掉 use strict 以便函数进入本作用域
const script = m[1];
const demoMatch = script.match(/var DEMO_BY_LANG = (\{[\s\S]*?\n\});/);
const DEMO_BY_LANG = demoMatch ? JSON.parse(demoMatch[1]) : null;
const DEMO = DEMO_BY_LANG ? DEMO_BY_LANG.zh : null;   // 旧断言沿用中文数据集
const body = script.replace('"use strict";', "")
  .replace(/var DEMO_BY_LANG = \{[\s\S]*?\n\};/, "");

// 最小 DOM 求值环境：定义用到的全局后 eval
const fnSrc = body;
eval(fnSrc.replace(/const |let /g, "var "));

let pass = 0, fail = 0;
function check(name, cond) { if (cond) { pass++; } else { fail++; console.log("FAIL:", name); } }

// parseSkills
const p = parseSkills("a-b: 处理挂号\n\nc-d: 解读报告\n坏名: x\ne-f\n");
check("parseSkills 好数量", p.skills.length === 2);
check("parseSkills 报错数", p.errs.length === 2);
check("parseSkills 重名", parseSkills("a-b: x\na-b: y").errs.length === 1);

// parseTasks
const pt = parseTasks("任务一 => a-b\n任务二\n");
check("parseTasks 带标签", pt.tasks[0].expected === "a-b");
check("parseTasks 无标签", pt.tasks[1].expected === null);

// extractChosen
const N = ["a-b", "c-d"];
check("chosen 标准", extractChosen('{"chosen": "a-b"}', N) === "a-b");
check("chosen 围栏", extractChosen('```json\n{"chosen":"c-d"}\n```', N) === "c-d");
check("chosen NONE", extractChosen("NONE", N) === "NONE");
check("chosen 垃圾", extractChosen("我觉得都行", N) === "INVALID");

// majority
const mj = majority(["a-b", "a-b", "a-b", "a-b", "c-d"]);
check("majority 一致率", mj.consistency === 0.8 && mj.chosen === "a-b");

// conflictReason
const cr = conflictReason("受理视力检查、报告相关咨询的登记与转接", "我的视力报告在哪查");
check("conflictReason 命中", cr.includes("视力") && cr.includes("报告"));

// matrixSvg
const svg = matrixSvg([[2, 0, 1], [0, 3, 0]], [{ name: "a-b", description: "甲职责" },
  { name: "c-d", description: "乙职责" }], ["a-b", "c-d", "NONE", "其他"]);
check("matrixSvg 结构", svg.startsWith("<svg") && svg.endsWith("</svg>") &&
  (svg.match(/<rect/g) || []).length === 10);
check("matrixSvg 行标签胶囊", (svg.match(/rx="10"/g) || []).length === 2);
const longSvg = matrixSvg([[1, 0], [0, 1]],
  [{ name: "scene-distillation-zine-v1-3", description: "抽象化重绘" },
   { name: "scenes-gathered-zine-v1-3", description: "拼贴海报" }],
  ["scene-distillation-zine-v1-3", "scenes-gathered-zine-v1-3", "NONE", "其他"]);
check("matrixSvg 长名列头截断+tooltip", longSvg.indexOf("<title>scene-distillation-zine-v1-3</title>") >= 0);
check("matrixSvg 长名行标签不被裁切", longSvg.indexOf("scene-distillation-zine-v1-3·") >= 0);

// 演示数据
check("DEMO 数据存在", !!DEMO && DEMO.matrix.length === 6 && DEMO.conflicts.length === 4);
check("DEMO 无隐私泄漏", html.indexOf("/Users/") < 0);

// Anthropic 分支
(async () => {
  const savedFetch = global.fetch;
  let captured = null;
  global.fetch = function(url, opts) {
    captured = { url, opts };
    return Promise.resolve({ ok: true, json: () => Promise.resolve(
      { content: [{ type: "text", text: '{"chosen": "a-b"}' }] }) });
  };
  const text = await llmCall(
    { provider: "anthropic", key: "k", model: "m" },
    "https://api.anthropic.com/v1",
    [{ role: "system", content: "系统提示" }, { role: "user", content: "用户输入" }], 60);
  check("anthropic 走 /messages", captured.url === "https://api.anthropic.com/v1/messages");
  check("anthropic 特殊头", captured.opts.headers["anthropic-dangerous-direct-browser-access"] === "true");
  check("anthropic 解析", text === '{"chosen": "a-b"}');
  global.fetch = savedFetch;

  // genTasksAuto 泄题过滤
  const skills3 = [{ name: "a-b", description: "甲的职责，处理挂号" },
                   { name: "c-d", description: "乙的职责，解读报告" }];
  const savedLlm = llmCall;
  llmCall = function(cfg, base, messages) {
    const prompt = messages[1].content;
    if (prompt.indexOf('"pairs"') >= 0) return Promise.resolve('{"pairs": [["a-b", "c-d"]]}');
    if (prompt.indexOf("任务问法") >= 0) return Promise.resolve('["我想用a-b挂号", "帮我预约门诊"]');
    if (prompt.indexOf("红队") >= 0)
      return Promise.resolve('{"first": ["挂号顺便看报告吗"], "second": ["报告窗口怎么走"]}');
    return Promise.reject(new Error("unexpected"));
  };
  const gen = await genTasksAuto({ key: "k", model: "m" }, "http://x", skills3, 2, 1);
  check("gen 泄题过滤", gen.tasks.every(x => x.t.indexOf("a-b") < 0));
  check("gen 灰区双向", gen.tasks.some(x => x.kind === "gray" && x.e === "a-b") &&
    gen.tasks.some(x => x.kind === "gray" && x.e === "c-d"));
  llmCall = savedLlm;

  // 流程回归：稳定冲突 → 建议生成（NONE 预期被过滤，不传给 genFixes）
  global.showStatus = global.hideStatus = function() {};
  global.$ = function(id) { return els[id] || { classList: { add() {}, remove() {} }, innerHTML: "" }; };
  const fixCalls = { calls: [] };
  const savedGen = genFixes;
  genFixes = function(cfg, base, fixable, byName) {
    fixCalls.calls.push(fixable.map(function(r) { return r.expected; }));
    return Promise.resolve([]);
  };
  const byNameMap = { "a-b": { name: "a-b", description: "x" } };
  const conflictsFlow = [
    { task: "正常冲突", expected: "a-b", chosen: "c-d" },
    { task: "过度接管", expected: "NONE", chosen: "a-b" },
  ];
  const triggered = triggerFixGeneration(conflictsFlow, byNameMap,
    [{ name: "a-b" }, { name: "c-d" }], { key: "k" }, "http://x");
  // 异步等 genFixes 链跑完
  await new Promise(function(r) { setTimeout(r, 10); });
  check("triggerFixGeneration 触发", triggered === true);
  check("genFixes 只收到可改写冲突", fixCalls.calls.length === 1 &&
    fixCalls.calls[0].length === 1 && fixCalls.calls[0][0] === "a-b");
  genFixes = savedGen;

  // 无可改写冲突 → 不触发
  const triggered2 = triggerFixGeneration(
    [{ task: "过度接管", expected: "NONE", chosen: "a-b" }], byNameMap, {}, "http://x");
  check("纯 NONE 冲突不触发建议生成", triggered2 === false);

  // #3: stopEval abort 在途请求
  const savedFetch3 = global.fetch;
  let sigRef = null;
  global.fetch = function(url, opts) {
    sigRef = opts.signal;
    return new Promise(function() {});  // 永不 settle，模拟在途
  };
  const p = llmCall({ provider: "openai", key: "k", model: "m" }, "http://x/v1",
    [{ role: "user", content: "t" }], 10);
  stopEval();
  check("stopEval abort 在途请求", !!sigRef && sigRef.aborted === true);
  global.fetch = savedFetch3;
  p.catch(function() {});

  const realPreflight = connectionPreflight;
  connectionPreflight = () => Promise.resolve({ok:true});

  // ===== 完整流程测试 A/B 共用的内部状态捕获 =====
  const hookCalls = [];
  globalThis.__atlasHook = function(byTask, info) {
    hookCalls.push({ byTask: JSON.parse(JSON.stringify(byTask)), info: info });
  };

  // ===== 完整流程测试 A：全部网络失败 → ERROR 票，保留错误原因 =====
  const el = function(id) { document.getElementById(id); return els[id]; };
  el("skills").value = "a-b: 甲\n\nc-d: 乙\n";
  el("tasks").value = "任务一 => a-b\n任务二 => c-d\n";
  el("samples").value = "1";
  el("provider").value = "openai"; el("key").value = "k";
  el("model").value = "m"; el("base").value = "http://x";
  const savedFetchA = global.fetch;
  global.fetch = function() { return Promise.reject(new Error("boom network")); };
  run();
  await new Promise(function(r) { setTimeout(r, 20); });
  check("流程A：错误原因保留", els["errbox"].textContent.indexOf("network") >= 0 && els["errbox"].textContent.indexOf("boom network") < 0);
  check("流程A：无 [object Object]", els["errbox"].textContent.indexOf("object Object") < 0);
  check("流程A：采样分类为 ERROR", hookCalls.length === 1 &&
    hookCalls[0].byTask.every(function(bt) { return bt.votes.join(",") === "ERROR"; }));
  check("流程A：fatal 计数正确", hookCalls[0].info.fatal === 2);
  global.fetch = savedFetchA;

  // ===== 完整流程测试 B：点击停止 → 在途请求 abort，采样 STOPPED =====
  const savedFetchB = global.fetch;
  const sigsB = [];
  global.fetch = function(url, opts) {
    sigsB.push(opts.signal);
    // 模拟真实在途请求：响应 abort 信号
    return new Promise(function(_, rej) {
      if (opts.signal) opts.signal.addEventListener("abort",
        function() { rej(new Error("AbortError")); });
    });
  };
  run();
  await new Promise(function(r) { setTimeout(r, 20); });
  check("流程B：两个请求均已发出", sigsB.length === 2);
  stopEval();
  await new Promise(function(r) { setTimeout(r, 20); });
  check("流程B：stop 后提示结果不完整", els["errbox"].textContent.indexOf("评测已停止") >= 0);
  check("流程B：不误报评测失败", els["conflicts"].innerHTML.indexOf("评测失败") < 0);
  check("流程B：在途请求全部 abort", sigsB.every(function(s) { return s.aborted; }));
  check("流程B：无 [object Object]", els["errbox"].textContent.indexOf("object Object") < 0);
  check("流程B：采样分类为 STOPPED", hookCalls.length === 2 &&
    hookCalls[1].byTask.every(function(bt) { return bt.votes.join(",") === "STOPPED"; }));
  check("流程B：STOPPED 计数正确", hookCalls[1].info.stoppedCount === 2 && hookCalls[1].info.fatal === 0);
  global.fetch = savedFetchB;
  delete globalThis.__atlasHook;

  const originalFetch = global.fetch;
  el("tasks").value = "test task => a-b";
  el("samples").value = "5";
  for (const valid of [1, 3, 4, 5]) {
    let count = 0;
    global.fetch = function() {
      return Promise.resolve({ok: true, json: () => Promise.resolve({choices: [
        {message: {content: count++ < valid ? "a-b" : "unparseable"}}
      ]})});
    };
    run();
    await new Promise(resolve => setTimeout(resolve, 20));
    check("web coverage boundary " + valid, valid < 4 ?
      els.errbox.textContent.includes("80%") && els.errbox.style.display !== "none" :
      els.errbox.style.display === "none");
  }
  const diagnostics = [{task: "x", expected: "a-b", votes: ["a-b", "a-b", "a-b", "INVALID", "INVALID"]}];
  render(diagnostics, [{name:"a-b", description:"a"}, {name:"c-d", description:"b"}], 5, "test");
  check("incomplete report never claims no conflicts", els.conflicts.innerHTML.includes("80%") &&
    !els.conflicts.innerHTML.includes(t("no_conflicts")));
  setLang("en");
  render(diagnostics, [{name:"a-b", description:"a"}, {name:"c-d", description:"b"}], 5, "test");
  check("English redraw preserves diagnostic warning", els.conflicts.innerHTML.includes("Evaluation failed") &&
    !els.conflicts.innerHTML.includes(t("no_conflicts")));
  setLang("zh");
  global.fetch = originalFetch;

  // ===== 演示数据（中英各一套，均由仓库内真实运行结果派生）=====
  check("演示数据含 zh/en 两套", !!DEMO_BY_LANG && Object.keys(DEMO_BY_LANG).sort().join() === "en,zh");
  Object.keys(DEMO_BY_LANG || {}).forEach(function(lang) {
    const D = DEMO_BY_LANG[lang];
    const sum = D.matrix.reduce(function(a, r) { return a + r.reduce(function(x, y) { return x + y; }, 0); }, 0);
    const stolen = D.matrix.reduce(function(a, r, i) {
      return a + r.reduce(function(x, y, j) { return x + y * (j !== i && j < D.skills.length ? 1 : 0); }, 0); }, 0);
    check("演示数据[" + lang + "] 矩阵行列与技能数吻合",
      D.matrix.length === D.skills.length && D.matrix.every(function(r) { return r.length === D.cols.length; }));
    check("演示数据[" + lang + "] 矩阵总数等于任务数", sum === D.meta.total);
    check("演示数据[" + lang + "] 命中+冲突+不稳定 = 任务数",
      D.meta.hits + D.conflicts.length + D.meta.unstable === D.meta.total);
    check("演示数据[" + lang + "] 冲突数与矩阵截胡格数一致", stolen === D.conflicts.length);
    check("演示数据[" + lang + "] 冲突条目合法",
      D.conflicts.every(function(c) {
        return c.task && D.cols.indexOf(c.expected) >= 0 && D.cols.indexOf(c.chosen) >= 0 &&
               /^\d+\/\d+$/.test(c.votes); }));
    check("演示数据[" + lang + "] 技能描述完整（未被截断）",
      D.skills.every(function(s) { return s.desc.length > 26; }));
    check("演示数据[" + lang + "] 有脚注文案", typeof D.meta.note === "string" && D.meta.note.length > 20);
    check("演示数据[" + lang + "] 脚注语言匹配",
      lang === "zh" ? /[\u4e00-\u9fff]/.test(D.meta.note) : !/[\u4e00-\u9fff]/.test(D.meta.note));
    check("演示数据[" + lang + "] 技能名与界面语言一致",
      lang === "zh" ? /[a-z]+-[a-z]/.test(D.skills[0].name) && /[\u4e00-\u9fff]/.test(D.skills[0].desc)
                    : !/[\u4e00-\u9fff]/.test(D.skills.map(function(s) { return s.desc; }).join("")));
  });
  check("演示数据与存档结果文件可复现", (function() {
    const fsx = require("fs"), p = require("path");
    const pairs = [["zh", "examples/results-demo-qwen.json"], ["en", "examples/results-demo-en-qwen.json"]];
    return pairs.every(function(pair) {
      const raw = JSON.parse(fsx.readFileSync(p.join(__dirname, "..", pair[1]), "utf-8"));
      const D = DEMO_BY_LANG[pair[0]];
      const names = D.skills.map(function(s) { return s.name; }).sort().join();
      const rawNames = raw.meta.skills.map(function(s) { return s.name; }).sort().join();
      return names === rawNames && raw.rows.length === D.meta.total &&
        raw.rows.filter(function(r) { return r.conflict; }).length === D.conflicts.length &&
        raw.meta.model === D.meta.model;
    });
  })());
  check("有对应语言的演示数据时用它自己那套",
    demoFor("zh") === DEMO_BY_LANG.zh && demoFor("en") === DEMO_BY_LANG.en);
  check("缺该语言时演示数据回落英文（非中文读者更可读）", demoFor("ja") === DEMO_BY_LANG.en);
  // 兜底链的最后一环：连英文都没有时仍要有数据，不能白屏
  const savedEn = DEMO_BY_LANG.en;
  delete DEMO_BY_LANG.en;
  check("两套都缺时兜底到中文", demoFor("ja") === DEMO_BY_LANG.zh);
  DEMO_BY_LANG.en = savedEn;
  check("兜底测试后状态已还原", demoFor("en") === DEMO_BY_LANG.en && !!DEMO_BY_LANG.en);

  // 行标签：英文描述取前几个词，不能退化成 name·name
  check("行标签 中文取首段中文", shortLabel("解读眼科检查报告，涵盖视力、眼压", "x") === "解读眼科检查报告");
  check("行标签 英文取前几个词", shortLabel("Handles booking, rescheduling and cancelling", "x") === "Handles booking");
  check("行标签 英文掐掉尾部虚词", shortLabel("Builds follow-up plans for post-op patients", "x") === "Builds follow-up plans");
  check("行标签 无描述时回退技能名", shortLabel("", "my-skill") === "my-skill");

  // ===== i18n =====
  const zhKeys = Object.keys(I18N.zh).sort().join(",");
  const enKeys = Object.keys(I18N.en).sort().join(",");
  check("i18n zh/en 键完全一致", zhKeys === enKeys && zhKeys.length > 0);
  check("i18n 无空值", Object.keys(I18N.zh).every(function(k) {
    return String(I18N.zh[k]).trim() && String(I18N.en[k]).trim(); }));
  const htmlKeys = (html.match(/data-i18n(?:-ph)?="([^"]+)"/g) || [])
    .map(function(m) { return m.replace(/data-i18n(-ph)?="/, "").replace(/"$/, ""); });
  check("i18n 页面标记的键都在字典里", htmlKeys.length >= 25 &&
    htmlKeys.every(function(k) { return I18N.zh[k] && I18N.en[k]; }));
  // 语言切换按钮里的「中文/English」是有意保留的（语言名用自身语言书写）
  check("i18n 无硬编码中文残留（button/h2/label 文案）",
    !/<button(?![^>]*data-lang)[^>]*>[\u4e00-\u9fff]/.test(html) &&
    !/<h2[^>]*>[\u4e00-\u9fff]/.test(html) && !/<label[^>]*>[\u4e00-\u9fff]/.test(html));
  applyI18n();   // 测试桩不会触发 DOMContentLoaded，这里显式执行一次
  check("默认语言跟随浏览器(zh)", LANG === "zh" && document.documentElement.lang === "zh-CN");
  check("?lang 参数优先", resolveLang("?lang=en", "zh", "zh-CN") === "en");
  check("localStorage 次之", resolveLang("", "en", "zh-CN") === "en");
  check("浏览器语言兜底", resolveLang("", null, "ja-JP") === "en" && resolveLang("", null, "zh-TW") === "zh");
  check("非法 lang 参数被忽略", resolveLang("?lang=xx", null, "zh-CN") === "zh");
  check("中文插值", t("votes", { n: 4, m: 5 }) === "（4/5 票）");
  setLang("en");
  check("切换到英文：文案变化", t("votes", { n: 4, m: 5 }) === " (4/5 votes)" &&
    t("run_btn") === "Run simulation" && document.documentElement.lang === "en");
  check("切换到英文：写入 localStorage", localStorage.getItem("atlas_lang") === "en");
  setLang("zh");
  check("切回中文", t("run_btn") === "开始模拟" && document.documentElement.lang === "zh-CN");

  // 演示数据按界面语言切换
  setLang("en");
  renderDemo();
  check("英文界面渲染英文演示数据集",
    els["skills"].value.indexOf("appointment-desk:") === 0 &&
    els["plains"].innerHTML.indexOf("Real CLI run") >= 0);
  setLang("zh");
  renderDemo();
  check("中文界面渲染中文演示数据集",
    els["skills"].value.indexOf("baogao-jiedu:") === 0 &&
    els["plains"].innerHTML.indexOf("真实模拟") >= 0);

  // 流程回归：演示按钮（曾因 loadDemo 未定义而完全失效）
  els["provider"].value = "openai";
  loadDemo();
  check("loadDemo 切换到演示模式", els["provider"].value === "demo");
  check("loadDemo 渲染热力图", els["matrix"].innerHTML.indexOf("<svg") >= 0);

  // 本机技能文件夹读取：frontmatter 解析
  const p1 = parseSkillMd("---\nname: a-b\ndescription: 处理挂号\n---\n\n正文", "fb");
  check("parseSkillMd 普通值", p1.name === "a-b" && p1.description === "处理挂号");
  const p2 = parseSkillMd('---\nname: "q-s"\ndescription: \'单引号\'\n---\n', "fb");
  check("parseSkillMd 去引号", p2.name === "q-s" && p2.description === "单引号");
  const p3 = parseSkillMd("---\nname: fold\ndescription: >-\n  line one\n  line two\n---\n", "fb");
  check("parseSkillMd 折行块", p3.description === "line one line two");
  const p4 = parseSkillMd("---\nname: lit\ndescription: |\n  l1\n  l2\n---\n", "fb");
  check("parseSkillMd 字面块", p4.description === "l1\nl2\n");
  const p5 = parseSkillMd("没有 frontmatter", "fallback-name");
  check("parseSkillMd 无 frontmatter 回退目录名", p5.name === "fallback-name" && p5.issues.length === 1);

  // 纯函数：文件列表 → SKILL.md 筛选（与 CLI 一致：跳过隐藏与噪音目录）
  const sel = selectSkillMdFiles([
    { name: "SKILL.md", webkitRelativePath: "skills/a/SKILL.md" },
    { name: "SKILL.md", webkitRelativePath: "skills/cat/b/SKILL.md" },
    { name: "SKILL.md", webkitRelativePath: "skills/.system/sys/SKILL.md" },
    { name: "SKILL.md", webkitRelativePath: "skills/node_modules/nm/SKILL.md" },
    { name: "README.md", webkitRelativePath: "skills/a/README.md" },
  ]);
  check("selectSkillMdFiles 递归+跳过隐藏", sel.picked.length === 2 && sel.hidden === 2);
  check("selectSkillMdFiles 目录名回退", sel.picked[1].folder === "b");

  // 纯函数：文件夹条目 → 粘贴行
  const fr = skillFolderRows([
    { path: "skills/a/SKILL.md", folder: "a", text: "---\nname: a-b\ndescription: 甲\n---\n" },
    { path: "skills/b/SKILL.md", folder: "b", text: "---\nname: b-c\ndescription: 乙\n---\n" },
    { path: "skills/c/SKILL.md", folder: "c", text: "---\nname: c-d\n---\n" },
  ]);
  check("skillFolderRows 提取技能", fr.rows.length === 2 && fr.rows[0].name === "a-b");
  check("skillFolderRows 跳过缺描述", fr.skipped.length === 1 && fr.skipped[0].indexOf("c-d") >= 0);
  check("skillFolderRows 折叠多行描述", skillFolderRows([
    { path: "s/m/SKILL.md", folder: "m", text: "---\nname: m\ndescription: |\n  第一行\n  第二行\n---\n" },
  ]).rows[0].description === "第一行 第二行");

  // 技能名玻璃胶囊
  check("chip 结构", chip("a-b") === '<span class="skill-chip">a-b</span>');
  check("chip red 变体", chip("c-d", "red").indexOf("skill-chip red") >= 0);
  check("chip 转义", chip("<x>").indexOf("&lt;") >= 0);
  loadDemo();
  check("skillStrip 展示全部技能", els["skillStrip"].innerHTML.split("skill-chip").length - 1 === 6);

  // #6: 预期 NONE
  const pn = parseTasks("无关任务 => NONE");
  check("parseTasks NONE", pn.tasks[0].expected === "NONE" && pn.errs.length === 0);

  // #5: llmCall 带 abort signal
  const savedLlmSig = global.fetch;
  let sigOpts = null;
  global.fetch = function(url, opts) {
    sigOpts = opts;
    return Promise.resolve({ ok: true, json: () => Promise.resolve(
      { content: [{ type: "text", text: "{}" }] }) });
  };
  llmCall({ provider: "anthropic", key: "k", model: "m" }, "https://x/v1",
    [{ role: "user", content: "t" }], 10);
  check("llmCall 传入 abort signal", !!sigOpts && !!sigOpts.signal);
  global.fetch = savedLlmSig;

  // #5: allSamplesInvalid 判定（与 CLI 的"评测失败"一致）
  check("allSamplesInvalid 全无效", allSamplesInvalid(
    [{ chosen: "INVALID" }, { chosen: "ERROR" }]) === true);
  check("allSamplesInvalid 有有效值", allSamplesInvalid(
    [{ chosen: "INVALID" }, { chosen: "a-b" }]) === false);
  check("allSamplesInvalid 空集", allSamplesInvalid([]) === false);

  // #7: 取消"记住配置" → 清除已保存配置
  const savedLlm2 = llmCall;
  llmCall = savedLlm;  // 保持引用一致（此处无实际调用）
  els["remember"].checked = false;
  els["provider"].value = "openai"; els["key"].value = "sk-x"; els["model"].value = "m"; els["base"].value = "http://x";
  saveCfg();
  check("saveCfg 取消勾选清除配置", removedKeys.indexOf("atlas_cfg") >= 0);
  els["remember"].checked = true;
  saveCfg();
  check("saveCfg 勾选写入配置", store["atlas_cfg"] !== undefined && store["atlas_cfg"].indexOf("sk-x") >= 0);
  llmCall = savedLlm2;

  const cases = JSON.parse(fs.readFileSync(path.join(__dirname, "frontmatter_cases.json"), "utf8"));
  check("CLI/web frontmatter shared cases", cases.every(function(c) {
    const parsed = parseSkillMd(c.text, "a-b");
    return !!parsed.fatal === c.fatal && (c.fatal || parsed.description === c.description);
  }));
  const rejected = skillFolderRows([
    {path: "good/SKILL.md", folder: "good", text: "---\nname: good\ndescription: valid\n---"},
    {path: "bad/SKILL.md", folder: "bad", text: "---\nname: bad\ndescription: >2\n  text\n---"}
  ]);
  check("invalid folder import blocks entire batch", rejected.rows.length === 0 && rejected.errors.length === 1);

  connectionPreflight=realPreflight;
  const featureFetch=global.fetch;
  let probeCalls=0;
  global.fetch=()=>{probeCalls++;return Promise.resolve({ok:false,status:401,text:()=>Promise.resolve('PRIVATE_VALUE')});};
  let probeError;
  try { await connectionPreflight({provider:'openai',key:'PRIVATE_VALUE',model:'test'},'https://x'); }
  catch(e){probeError=e;}
  check('preflight authentication sanitized',probeCalls===1 && probeError.diagnostic.code==='authentication' && !probeError.message.includes('PRIVATE_VALUE'));
  check('browser network diagnosis honest',diagnosticText(safeDiagnostic(new TypeError('PRIVATE_VALUE'))).includes('CORS'));
  global.fetch=()=>Promise.resolve({ok:true,json:()=>Promise.resolve({choices:[{message:{content:'not a choice'}}]})});
  let invalidProbe=false;
  try {await connectionPreflight({provider:'openai',key:'k',model:'m'},'https://x');}catch(e){invalidProbe=e.diagnostic.code==='invalid_response';}
  check('unparseable preflight blocks',invalidProbe);
  global.fetch=()=>Promise.resolve({ok:true,json:()=>Promise.resolve({wrong:'PRIVATE_VALUE'})});
  let malformedProbe=false;
  try{await connectionPreflight({provider:'openai',key:'k',model:'m'},'https://x');}
  catch(e){malformedProbe=e.diagnostic.code==='invalid_response' && !e.message.includes('PRIVATE_VALUE');}
  check('malformed response is not misclassified as network',malformedProbe);

  const draft=parseTaskDraft([{t:'line 1\nline 2 => quoted',e:'a-b',hint:true,id:'case-17',kind:'gray',pair:['a-b','c-d']}]);
  check('import never trusts suggested labels',draft[0].reviewed===false);
  el('skills').value='a-b: candidate a\nc-d: candidate c';
  reviewDraft=draft;
  let unreviewed=false;try{reviewedTasks();}catch(e){unreviewed=true;}
  check('unreviewed task blocked',unreviewed);
  editReview(0,'reviewed',true);applyReviewedTasks();
  check('multiline task survives review and JSON parsing',parseTasks(el('tasks').value).tasks[0].task===draft[0].t);
  reviewCurrentTasks();editReview(0,'reviewed',true);applyReviewedTasks();
  const retained=JSON.parse(el('tasks').value)[0];
  check('review preserves task provenance',retained.id==='case-17' && retained.kind==='gray' && retained.pair.join(',')==='a-b,c-d' && retained.hint===true && !('reviewed' in retained));
  editReview(0,'e','c-d');
  check('editing invalidates confirmation',!reviewDraft[0].reviewed && reviewedText===null);
  let refused=false;try{parseTaskDraft([null]);}catch(e){refused=true;}
  check('invalid draft rejected',refused);
  reviewDraft=[{t:'<img onerror=x>',e:'a-b',reviewed:false}];renderReview();
  check('review display escapes imported task',!el('reviewTable').innerHTML.includes('<img'));
  function bt(votes,expected){return {task:'test',expected:expected||'a-b',votes:votes};}
  const five=x=>Array(5).fill(x);
  [
    [five('c-d'),five('a-b'),'improved',0],
    [five('a-b'),five('c-d'),'regressed',1],
    [five('a-b'),five('a-b'),'unchanged_correct',0],
    [five('c-d'),five('NONE'),'persistent_error',0],
    [['a-b','a-b','a-b','c-d','c-d'],five('a-b'),'review',3],
    [['a-b','a-b','a-b','ERROR','ERROR'],five('a-b'),'failed',2]
  ].forEach(function(c){const r=pairedComparison([bt(c[0])],[bt(c[1])],['a-b','c-d'],5);check('web paired '+c[2],r.pairs[0].status===c[2]&&r.exit_code===c[3]);});
  check('web failure outranks regression',pairedComparison([bt(five('a-b')),bt(five('a-b'))],
    [bt(five('c-d')),bt(five('ERROR'))],['a-b','c-d'],5).exit_code===2);
  el('baselineSkills').value='c-d: baseline c\na-b: baseline a';
  el('key').value='PRIVATE_VALUE';el('provider').value='openai';el('model').value='test';el('base').value='https://x';
  reviewDraft=[{t:'first task',e:'a-b',reviewed:true},{t:'second task',e:'c-d',reviewed:true}];applyReviewedTasks();
  let requests=[];
  global.fetch=(url,opts)=>{
    const body=JSON.parse(opts.body);requests.push(body);
    const content=body.messages[1].content;
    const chosen=content.includes('Connection test')?'NONE':content.includes('candidate')?'a-b':'c-d';
    return Promise.resolve({ok:true,json:()=>Promise.resolve({choices:[{message:{content:chosen}}]})});
  };
  await runComparison();
  check('full web comparison counts and preflight',requests.length===21 && window.__lastComparison.exit_code===1 &&
    window.__lastComparison.counts.improved===1&&window.__lastComparison.counts.regressed===1);
  check('comparison export excludes credentials',!JSON.stringify(window.__lastComparison).includes('PRIVATE_VALUE'));
  check('fixed five samples despite selector',window.__lastComparison.meta.samples===5);
  check('comparison shows description diff',window.__lastComparison.changes.length===2);
  const previousRun=window.__lastComparison.meta.run_id;
  el('baselineSkills').value='invalid baseline ignored for AA';requests=[];
  await runComparison(true);
  check('AA uses identical catalogs and independent calls',requests.length===21 && window.__lastComparison.meta.comparison_type==='AA' && window.__lastComparison.changes.length===0 && JSON.stringify(window.__lastComparison.collections.baseline)===JSON.stringify(window.__lastComparison.collections.candidate));
  check('AA report labels variation and has new run identity',window.__lastComparison.meta.run_id!==previousRun && el('comparisonSummary').textContent.includes(t('aa_note')));
  el('baselineSkills').value='c-d: baseline c\na-b: baseline a';
  requests=[];el('tasks').value+=' ';
  await runComparison();check('task edits require renewed review',requests.length===0);
  applyReviewedTasks();el('baselineSkills').value='a-b: baseline';requests=[];
  await runComparison();check('mismatched collections stop before network',requests.length===0);
  el('baselineSkills').value='a-b: baseline a\nc-d: baseline c';
  let failures=0;global.fetch=()=>{failures++;return Promise.reject(new TypeError('PRIVATE_VALUE'));};
  await runComparison();
  check('comparison preflight failure prevents batch',failures===1&&window.__lastComparison===null&&!el('errbox').textContent.includes('PRIVATE_VALUE'));
  failures=0;await run();check('single evaluation preflight prevents batch',failures===1);
  failures=0;await genTasks();check('generation preflight prevents batch',failures===1);
  let pendingSignals=[];
  global.fetch=(url,opts)=>{
    if(JSON.parse(opts.body).messages[1].content.includes('Connection test'))
      return Promise.resolve({ok:true,json:()=>Promise.resolve({choices:[{message:{content:'NONE'}}]})});
    pendingSignals.push(opts.signal);
    return new Promise((resolve,reject)=>opts.signal.addEventListener('abort',()=>{const e=new Error();e.name='AbortError';reject(e);}));
  };
  const stoppedComparison=runComparison();await new Promise(resolve=>setTimeout(resolve,20));stopEval();await stoppedComparison;
  check('comparison stop aborts and marks incomplete',pendingSignals.length>0&&pendingSignals.every(x=>x.aborted)&&window.__lastComparison.stopped&&window.__lastComparison.exit_code===2);
  global.fetch=featureFetch;

  const cv=taskCoverage([{t:'x',e:'a-b'},{t:' x ',e:'a-b',kind:'gray'},{t:'n',e:'NONE'}],['a-b','c-d']);
  check('coverage counts labels and kinds',cv.skills['a-b'].positive===1 && cv.skills['a-b'].gray===1 && cv.none_tasks===1);
  check('coverage reports uncovered skills and duplicates',cv.uncovered.join(',')==='c-d' && cv.duplicates[0].count===2);
  const originalGen=genFixes, originalRender=renderFixes;
  let resolveOld, oldRenders=0;
  genFixes=()=>new Promise(resolve=>{resolveOld=resolve;});
  renderFixes=()=>{oldRenders++;};
  evalStopped=false; beginOperation();
  triggerFixGeneration([{expected:'a-b'}],{'a-b':{}},[],{},'https://example.invalid');
  beginOperation(); resolveOld([]); await new Promise(resolve=>setTimeout(resolve,0));
  check('late suggestion cannot overwrite a newer operation',oldRenders===0);
  triggerFixGeneration([{expected:'a-b'}],{'a-b':{}},[],{},'https://example.invalid');
  resolveOld([]); await new Promise(resolve=>setTimeout(resolve,0));
  check('current suggestion still renders',oldRenders===1);
  genFixes=originalGen;renderFixes=originalRender;

  const savedPreflight=connectionPreflight, savedAuto=genTasksAuto;
  connectionPreflight=()=>Promise.resolve({ok:true});
  const grayTask={id:'gray-1',t:'Boundary task',e:'a-b',kind:'gray',pair:'a-b↔c-d'};
  genTasksAuto=()=>Promise.resolve({tasks:[grayTask],warnings:[]});
  el('skills').value='a-b: Weather\nc-d: Calendar';
  el('provider').value='openai';el('key').value='FAKE_TEST_KEY';el('model').value='test';el('base').value='https://example.invalid';
  for(const prior of ['', 'Existing task => c-d', JSON.stringify([{id:'old-1',t:'Existing task',e:'c-d',kind:'positive'}])]) {
    el('tasks').value=prior;
    await genTasks();reviewCurrentTasks();
    reviewDraft.forEach(r=>{r.reviewed=true;});applyReviewedTasks();
    const exported=reviewedTasks(), row=exported[exported.length-1];
    check('generated gray metadata survives review: '+prior,JSON.stringify(row)===JSON.stringify(grayTask));
    const coverage=taskCoverage(exported,['a-b','c-d']);
    check('generated gray coverage and existing tasks: '+prior,coverage.skills['a-b'].gray===1 && coverage.skills['a-b'].positive===0 && exported.length===(prior?2:1));
  }
  connectionPreflight=savedPreflight;genTasksAuto=savedAuto;

  // 文档自校验是元检查，不计入产品断言数；先冻结计数器，否则会出现「自己数自己」的循环
  const productTotal = pass + fail;
  const metaStart = pass + fail;

  // ===== 文档数字自校验 =====
  // 测试数已经漂移过三次（四份译文停在 58/19、CI 步骤名停在 25、徽章停在 90/91），
  // 这里把它们钉住：CLI 用例数可静态推导（一个 def test_ 就是一个用例，无参数化），
  // 网页断言数就是本文件刚跑出的总数。六份 README 写得不对，这里直接变红。
  const READMES = ["README.md", "README.zh-CN.md", "README.ja.md", "README.ko.md", "README.es.md", "README.de.md"];
  // PROJECT.md / CONTRIBUTING.md 也写测试数，一起管（PROJECT.md 曾停在「34 项测试」）
  const DOCS = READMES.concat(["PROJECT.md", "CONTRIBUTING.md"]);
  const cliCount = (fs.readFileSync(path.join(__dirname, "test_atlas.py"), "utf-8").match(/def test_/g) || []).length;
  const webCount = productTotal;   // 只算产品断言，不含本节自校验
  // 按 token 边界取数字：否则徽章颜色码 "0f6e56"/"3b6d11"（含数字）会被误判成过期测试数
  const NUM_RE = /(?<![0-9A-Za-z])\d+(?![0-9A-Za-z])/g;
  const numsIn = (line) => String(line).match(NUM_RE) || [];
  const hasNum = (line, n) => numsIn(line).indexOf(String(n)) >= 0;
  // 只看「提到测试脚本的行」上的数字，且忽略 <30 的（"node >= 18"、"Python 3.10" 之类不是测试数）
  const counts = [cliCount, webCount];
  DOCS.forEach(function(f) {
    const lines = fs.readFileSync(path.join(__dirname, "..", f), "utf-8").split("\n")
      .filter(l => /test_atlas\.py|web_smoke\.cjs/.test(l));
    const stale = [].concat.apply([], lines.map(numsIn))
      .filter(n => Number(n) >= 30 && counts.indexOf(Number(n)) < 0);
    check("文档数字[" + f + "] 提到测试数的行无过期计数", lines.length > 0 && stale.length === 0);
  });
  READMES.forEach(function(f) {
    const lines = fs.readFileSync(path.join(__dirname, "..", f), "utf-8").split("\n");
    const cliLines = lines.filter(l => l.indexOf("test_atlas.py") >= 0);
    const webLines = lines.filter(l => l.indexOf("web_smoke.cjs") >= 0);
    check("文档数字[" + f + "] 明确写了 CLI 数 " + cliCount + "（徽章 + 命令注释）",
      cliLines.length > 0 && cliLines.every(l => hasNum(l, cliCount)));
    check("文档数字[" + f + "] 明确写了网页断言数 " + webCount,
      webLines.length === 1 && hasNum(webLines[0], webCount));
  });
  check("文档数字[PROJECT.md] 明确写了 CLI 数 " + cliCount, (function() {
    return fs.readFileSync(path.join(__dirname, "..", "PROJECT.md"), "utf-8")
      .split("\n").filter(l => l.indexOf("test_atlas.py") >= 0).every(l => hasNum(l, cliCount));
  })());

  const metaTotal = (pass + fail) - metaStart;
  console.log(`web smoke: ${productTotal} 项产品断言 + ${metaTotal} 项文档自校验，通过 ${pass}`);
  process.exit(fail ? 1 : 0);
})();
