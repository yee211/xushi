#!/usr/bin/env node
// WXML 标签配对与事件绑定静态检查（CI 与本地共用）
const fs = require('fs');
const path = require('path');
const root = path.resolve(__dirname, '..');
const files = ['pages/index/index.wxml', 'pages/editor/editor.wxml', 'pages/agent/agent.wxml',
  'pages/feedback/feedback.wxml'];
const voids = new Set(['input', 'image']);
let failed = false;
for (const rel of files) {
  const src = fs.readFileSync(path.join(root, rel), 'utf8');
  const stack = [];
  const re = /<(\/)?([a-zA-Z][\w-]*)((\"[^\"]*\"|'[^']*'|[^>"'])*?)(\/)?>/g;
  let m;
  while ((m = re.exec(src))) {
    const [, closing, tag, , , self] = m;
    if (self || voids.has(tag)) continue;
    if (closing) {
      const top = stack.pop();
      if (top !== tag) { console.error(`${rel}: mismatched </${tag}>, expect </${top}>`); failed = true; break; }
    } else stack.push(tag);
  }
  if (stack.length) { console.error(`${rel}: unclosed ${stack.join(',')}`); failed = true; }
  if (/<=/.test(src)) { console.error(`${rel}: "<=" inside expression breaks WXML parser`); failed = true; }
  const jsRel = rel.replace('.wxml', '.js');
  const js = fs.readFileSync(path.join(root, jsRel), 'utf8');
  const bindRe = /(?:bind|catch)[a-z]+="([A-Za-z]+)"/g;
  while ((m = bindRe.exec(src))) {
    if (!js.includes(m[1] + '(')) { console.error(`${rel}: handler ${m[1]} missing in ${jsRel}`); failed = true; }
  }
}
process.exit(failed ? 1 : 0);
