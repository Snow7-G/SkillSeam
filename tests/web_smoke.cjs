// SkillSeam web smoke test（node >= 18，无依赖；CI 与本地共用）
// 运行: node tests/web_smoke.cjs
const fs = require("fs");
const path = require("path");

const els = {};
global.document = { getElementById: (id) => {
    if (!els[id]) els[id] = { addEventListener() {}, value: "", checked: true, style: {},
      classList: { toggle() {}, remove() {}, add() {} }, innerHTML: "", textContent: "",
      disabled: false, scrollIntoView() {} };
    return els[id];
  }, querySelectorAll: () => [] };
const store = {};
const removedKeys = [];
global.localStorage = {
  getItem: (k) => (k in store ? store[k] : null),
  setItem: (k, v) => { store[k] = String(v); },
  removeItem: (k) => { removedKeys.push(k); delete store[k]; },
};
global.fetch = () => Promise.reject(new Error("no network"));

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
function t(name, cond) { if (cond) { pass++; } else { fail++; console.log("FAIL:", name); } }

// parseSkills
const p = parseSkills("a-b: 处理挂号\n\nc-d: 解读报告\n坏名: x\ne-f\n");
t("parseSkills 好数量", p.skills.length === 2);
t("parseSkills 报错数", p.errs.length === 2);
t("parseSkills 重名", parseSkills("a-b: x\na-b: y").errs.length === 1);

// parseTasks
const pt = parseTasks("任务一 => a-b\n任务二\n");
t("parseTasks 带标签", pt.tasks[0].expected === "a-b");
t("parseTasks 无标签", pt.tasks[1].expected === null);

// extractChosen
const N = ["a-b", "c-d"];
t("chosen 标准", extractChosen('{"chosen": "a-b"}', N) === "a-b");
t("chosen 围栏", extractChosen('```json\n{"chosen":"c-d"}\n```', N) === "c-d");
t("chosen NONE", extractChosen("NONE", N) === "NONE");
t("chosen 垃圾", extractChosen("我觉得都行", N) === "INVALID");

// majority
const mj = majority(["a-b", "a-b", "a-b", "a-b", "c-d"]);
t("majority 一致率", mj.consistency === 0.8 && mj.chosen === "a-b");

// conflictReason
const cr = conflictReason("受理视力检查、报告相关咨询的登记与转接", "我的视力报告在哪查");
t("conflictReason 命中", cr.includes("视力") && cr.includes("报告"));

// matrixSvg
const svg = matrixSvg([[2, 0, 1], [0, 3, 0]], [{ name: "a-b", description: "甲职责" },
  { name: "c-d", description: "乙职责" }], ["a-b", "c-d", "NONE", "其他"]);
t("matrixSvg 结构", svg.startsWith("<svg") && svg.endsWith("</svg>") &&
  (svg.match(/<rect/g) || []).length === 8);

// 演示数据
t("DEMO 数据存在", !!DEMO && DEMO.matrix.length === 6 && DEMO.conflicts.length === 4);
t("DEMO 无隐私泄漏", html.indexOf("/Users/") < 0);

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
  t("anthropic 走 /messages", captured.url === "https://api.anthropic.com/v1/messages");
  t("anthropic 特殊头", captured.opts.headers["anthropic-dangerous-direct-browser-access"] === "true");
  t("anthropic 解析", text === '{"chosen": "a-b"}');
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
  t("gen 泄题过滤", gen.tasks.every(x => x.t.indexOf("a-b") < 0));
  t("gen 灰区双向", gen.tasks.some(x => x.kind === "gray" && x.e === "a-b") &&
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
  t("triggerFixGeneration 触发", triggered === true);
  t("genFixes 只收到可改写冲突", fixCalls.calls.length === 1 &&
    fixCalls.calls[0].length === 1 && fixCalls.calls[0][0] === "a-b");
  genFixes = savedGen;

  // 无可改写冲突 → 不触发
  const triggered2 = triggerFixGeneration(
    [{ task: "过度接管", expected: "NONE", chosen: "a-b" }], byNameMap, {}, "http://x");
  t("纯 NONE 冲突不触发建议生成", triggered2 === false);

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
  t("stopEval abort 在途请求", !!sigRef && sigRef.aborted === true);
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
  t("流程A：错误原因保留", els["errbox"].textContent.indexOf("boom network") >= 0);
  t("流程A：无 [object Object]", els["errbox"].textContent.indexOf("object Object") < 0);
  t("流程A：采样分类为 ERROR", hookCalls.length === 1 &&
    hookCalls[0].byTask.every(function(bt) { return bt.votes.join(",") === "ERROR"; }));
  t("流程A：fatal 计数正确", hookCalls[0].info.fatal === 2);
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
  t("流程B：两个请求均已发出", sigsB.length === 2);
  stopEval();
  await new Promise(function(r) { setTimeout(r, 20); });
  t("流程B：stop 后提示结果不完整", els["errbox"].textContent.indexOf("评测已停止") >= 0);
  t("流程B：不误报评测失败", els["conflicts"].innerHTML.indexOf("评测失败") < 0);
  t("流程B：在途请求全部 abort", sigsB.every(function(s) { return s.aborted; }));
  t("流程B：无 [object Object]", els["errbox"].textContent.indexOf("object Object") < 0);
  t("流程B：采样分类为 STOPPED", hookCalls.length === 2 &&
    hookCalls[1].byTask.every(function(bt) { return bt.votes.join(",") === "STOPPED"; }));
  t("流程B：STOPPED 计数正确", hookCalls[1].info.stoppedCount === 2 && hookCalls[1].info.fatal === 0);
  global.fetch = savedFetchB;
  delete globalThis.__atlasHook;

  // 流程回归：演示按钮（曾因 loadDemo 未定义而完全失效）
  els["provider"].value = "openai";
  loadDemo();
  t("loadDemo 切换到演示模式", els["provider"].value === "demo");
  t("loadDemo 渲染热力图", els["matrix"].innerHTML.indexOf("<svg") >= 0);

  // #6: 预期 NONE
  const pn = parseTasks("无关任务 => NONE");
  t("parseTasks NONE", pn.tasks[0].expected === "NONE" && pn.errs.length === 0);

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
  t("llmCall 传入 abort signal", !!sigOpts && !!sigOpts.signal);
  global.fetch = savedLlmSig;

  // #5: allSamplesInvalid 判定（与 CLI 的"评测失败"一致）
  t("allSamplesInvalid 全无效", allSamplesInvalid(
    [{ chosen: "INVALID" }, { chosen: "ERROR" }]) === true);
  t("allSamplesInvalid 有有效值", allSamplesInvalid(
    [{ chosen: "INVALID" }, { chosen: "a-b" }]) === false);
  t("allSamplesInvalid 空集", allSamplesInvalid([]) === false);

  // #7: 取消"记住配置" → 清除已保存配置
  const savedLlm2 = llmCall;
  llmCall = savedLlm;  // 保持引用一致（此处无实际调用）
  els["remember"].checked = false;
  els["provider"].value = "openai"; els["key"].value = "sk-x"; els["model"].value = "m"; els["base"].value = "http://x";
  saveCfg();
  t("saveCfg 取消勾选清除配置", removedKeys.indexOf("atlas_cfg") >= 0);
  els["remember"].checked = true;
  saveCfg();
  t("saveCfg 勾选写入配置", store["atlas_cfg"] !== undefined && store["atlas_cfg"].indexOf("sk-x") >= 0);
  llmCall = savedLlm2;

  console.log(`web smoke: ${pass + fail} 项，通过 ${pass}`);
  process.exit(fail ? 1 : 0);
})();
