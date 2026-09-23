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
const demoMatch = script.match(/var DEMO = (\{.*?\});\n/s);
const DEMO = demoMatch ? JSON.parse(demoMatch[1]) : null;
const body = script.replace('"use strict";', "")
  .replace(/var DEMO = \{.*?\};\n/s, "");

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
  check("流程A：错误原因保留", els["errbox"].textContent.indexOf("boom network") >= 0);
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
  check("parseSkillMd 字面块", p4.description === "l1\nl2");
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

  console.log(`web smoke: ${pass + fail} 项，通过 ${pass}`);
  process.exit(fail ? 1 : 0);
})();
