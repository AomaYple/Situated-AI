// PDX 脚本解析器原型（Victoria 3）
// 目的：验证 Node.js 是否适合做游戏文件的扫描与核实
//
// 设计要点 —— 每一条都对应本会话中踩过的真实坑：
//   1. 花括号深度解析，而非缩进   → 官方文件混用 tab 与 4 空格
//   2. 注释剥离要引号感知         → 字符串里可能含 #
//   3. 键名字符集用「非空白非等号」 → 存在含连字符的键（32 个）
//   4. 识别 INJECT:/REPLACE: 前缀  → 6 个引擎级关键字
//   5. UTF-8 原生读取             → 规避 PS 5.1 的 GBK 解码陷阱

import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join, extname } from 'node:path';

const PREFIXES = [
  'REPLACE_OR_CREATE', 'INJECT_OR_CREATE', 'TRY_INJECT',
  'TRY_REPLACE', 'REPLACE', 'INJECT',
];

/** 剥离行内注释（引号感知）+ 统计花括号净增量 */
function scanLine(raw) {
  let inQuote = false;
  let clean = '';
  let delta = 0;
  for (let i = 0; i < raw.length; i++) {
    const c = raw[i];
    if (c === '"') { inQuote = !inQuote; clean += c; continue; }
    if (c === '#' && !inQuote) break;          // 注释开始，丢弃本行余下部分
    if (!inQuote) {
      if (c === '{') delta++;
      else if (c === '}') delta--;
    }
    clean += c;
  }
  return { text: clean.trim(), delta };
}

/** 解析一个文件，返回 { keys, prefixed, maxDepth } */
function parseFile(path) {
  const src = readFileSync(path, 'utf8');        // Node 原生 UTF-8，无 BOM 问题
  const keys = [];
  const prefixed = [];
  let depth = 0;
  let maxDepth = 0;

  for (const raw of src.split(/\r?\n/)) {
    const { text, delta } = scanLine(raw);

    // 只在「深度 0」记录顶层键 —— 这是判断顶层定义的唯一可靠方式
    if (depth === 0 && text) {
      // 带功能前缀？
      let body = text;
      let pfx = null;
      for (const p of PREFIXES) {
        if (body.startsWith(p + ':')) { pfx = p; body = body.slice(p.length + 1); break; }
      }
      // 键名 = 值 / 键名 = {   （键名允许连字符、点号）
      const m = body.match(/^([^\s={]+)\s*=/);
      if (m) {
        if (pfx) prefixed.push({ prefix: pfx, key: m[1] });
        else keys.push(m[1]);
      }
    }
    depth += delta;
    if (depth > maxDepth) maxDepth = depth;
  }
  return { keys, prefixed, maxDepth };
}

/** 递归收集目录下所有 .txt */
function collect(dir, out = []) {
  for (const e of readdirSync(dir)) {
    const p = join(dir, e);
    const st = statSync(p);
    if (st.isDirectory()) collect(p, out);
    else if (extname(e) === '.txt') out.push(p);
  }
  return out;
}

// ── 自检：拿已知数字对照 ────────────────────────────────
const GAME = 'C:\\Program Files (x86)\\Steam\\steamapps\\common\\Victoria 3\\game\\common';
const EXPECT = {
  static_modifiers: 6121,
  modifier_type_definitions: 2364,
  production_methods: 436,
  character_templates: 2011,
  buildings: 115,
  laws: 138,
};

console.log('目录'.padEnd(30) + '文件'.padStart(6) + '唯一键'.padStart(8) + '期望'.padStart(8) + '  结果');
console.log('-'.repeat(70));

let allOk = true;
const t0 = Date.now();
let fileCount = 0;

for (const [dir, expect] of Object.entries(EXPECT)) {
  const files = collect(join(GAME, dir));
  fileCount += files.length;
  const set = new Set();
  for (const f of files) for (const k of parseFile(f).keys) set.add(k);
  const ok = set.size === expect;
  if (!ok) allOk = false;
  console.log(
    dir.padEnd(30) + String(files.length).padStart(6) +
    String(set.size).padStart(8) + String(expect).padStart(8) +
    (ok ? '  ✅' : '  ❌')
  );
}

const ms = Date.now() - t0;
console.log('-'.repeat(70));
console.log(`全部一致: ${allOk ? '是' : '否'}   耗时 ${ms} ms   扫描 ${fileCount} 个文件`);

// ── 演示：检测功能前缀 ──────────────────────────────────
const ws = 'C:\\Program Files (x86)\\Steam\\steamapps\\workshop\\content\\529340';
const counts = {};
try {
  for (const mod of readdirSync(ws)) {
    const modDir = join(ws, mod);
    if (!statSync(modDir).isDirectory()) continue;
    for (const f of collect(modDir)) {
      for (const { prefix } of parseFile(f).prefixed) {
        counts[prefix] = (counts[prefix] ?? 0) + 1;
      }
    }
  }
  console.log('\n功能前缀统计（23 个 mod）:');
  for (const [k, v] of Object.entries(counts).sort((a, b) => b[1] - a[1])) {
    console.log('  ' + k.padEnd(22) + String(v).padStart(6));
  }
} catch (e) {
  console.log('\n前缀统计跳过: ' + e.message);
}
