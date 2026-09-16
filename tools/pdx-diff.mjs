// 找出「深度法」能捕获、但「缩进法」漏掉的键
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join, extname } from 'node:path';

function scanLine(raw) {
  let inQuote = false, clean = '', delta = 0;
  for (let i = 0; i < raw.length; i++) {
    const c = raw[i];
    if (c === '"') { inQuote = !inQuote; clean += c; continue; }
    if (c === '#' && !inQuote) break;
    if (!inQuote) { if (c === '{') delta++; else if (c === '}') delta--; }
    clean += c;
  }
  return { text: clean.trim(), delta, raw };
}

function collect(dir, out = []) {
  for (const e of readdirSync(dir)) {
    const p = join(dir, e);
    if (statSync(p).isDirectory()) collect(p, out);
    else if (extname(e) === '.txt') out.push(p);
  }
  return out;
}

const DIR = 'C:\\Program Files (x86)\\Steam\\steamapps\\common\\Victoria 3\\game\\common\\static_modifiers';

const byDepth = new Set();
const byIndent = new Set();
const onlyDepth = [];

for (const f of collect(DIR)) {
  const lines = readFileSync(f, 'utf8').split(/\r?\n/);
  let depth = 0;
  for (let n = 0; n < lines.length; n++) {
    const { text, delta, raw } = scanLine(lines[n]);

    // 深度法：花括号深度 == 0
    let keyAtDepth0 = null;
    if (depth === 0 && text) {
      const m = text.match(/^([^\s={]+)\s*=\s*\{/);
      if (m) { keyAtDepth0 = m[1]; byDepth.add(m[1]); }
    }
    // 缩进法：行首必须无任何空白
    const m2 = raw.match(/^([^\s=#][^\s=]*)\s*=\s*\{/);
    if (m2) byIndent.add(m2[1]);

    if (keyAtDepth0 && !m2) {
      onlyDepth.push({ file: f.split('\\').pop(), line: n + 1, key: keyAtDepth0, raw: raw.slice(0, 60) });
    }
    depth += delta;
  }
}

console.log('深度法唯一键:', byDepth.size);
console.log('缩进法唯一键:', byIndent.size);
console.log('');
console.log('=== 只有深度法能捕获的键（即缩进法漏掉的）===');
for (const d of onlyDepth) {
  console.log(`  ${d.key}`);
  console.log(`      ${d.file}:${d.line}`);
  console.log(`      原文: [${d.raw.replace(/\t/g, '<TAB>')}]`);
}
