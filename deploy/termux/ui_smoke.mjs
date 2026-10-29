// On-device check of the web UI against the running hg-runtime (real service, real local model).
//
// usage: HG_JSDOM_DIR=<dir with node_modules/jsdom> node ui_smoke.mjs <port> <out.json> "<question>" [general|notes]
//
// Loads http://127.0.0.1:<port>/ui/ with jsdom, runs the page's own app.js and styles.css as served
// by the release, types the service token into the Connection screen (read here from
// ~/.config/hg/runtime-service.token; never printed, never put in argv or the report), clicks
// "Lưu và kiểm tra", then sends the question with the Send button and waits for the answer the
// page renders from POST /v1/chat. jsdom has no fetch, so the page gets Node's fetch through a
// wrapper that refuses any URL outside the page's own origin and records method + path + status.
// The report holds what the page displayed (DOM text, labels) and the request list; it contains
// no token. Exit 0 only if the page showed READY and an answer with outcome ANSWERED.
//
// Install jsdom once into a private evidence directory (not the release):
//   npm install --prefix ~/hg-v1-evidence/ui-smoke jsdom@26
import { readFileSync, writeFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { homedir } from 'node:os';
import { join } from 'node:path';

const [port, outPath, question, mode = 'general'] = process.argv.slice(2);
if (!port || !outPath || !question) {
  console.error('usage: node ui_smoke.mjs <port> <out.json> "<question>" [general|notes]');
  process.exit(2);
}
const require = createRequire(join(process.env.HG_JSDOM_DIR || '.', 'node_modules', 'x.js'));
const { JSDOM, VirtualConsole } = require('jsdom');

const origin = `http://127.0.0.1:${Number(port)}`;
const token = readFileSync(join(homedir(), '.config', 'hg', 'runtime-service.token'), 'utf8').replace(/\n$/, '');
const report = { origin, question, mode, requests: [], console: [], checks: {} };
const started = Date.now();

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function until(fn, timeoutMs, label) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const v = fn();
    if (v) return v;
    await sleep(250);
  }
  throw new Error('timeout waiting for ' + label);
}

const vc = new VirtualConsole();
vc.on('jsdomError', (e) => report.console.push({ type: 'jsdomError', text: String(e && e.message) }));
['log', 'warn', 'error'].forEach((t) => vc.on(t, (m) => report.console.push({ type: t, text: String(m) })));

const dom = await JSDOM.fromURL(origin + '/ui/', {
  runScripts: 'dangerously', resources: 'usable', pretendToBeVisual: true, virtualConsole: vc,
  beforeParse(window) {
    window.fetch = async (input, init = {}) => {
      const url = new URL(String(input), window.location.href);
      if (url.origin !== origin) {
        report.requests.push({ method: init.method || 'GET', url: url.href, refused: true });
        throw new window.TypeError('cross-origin request refused by ui_smoke');
      }
      const res = await fetch(url, { method: init.method, headers: init.headers, body: init.body,
                                     cache: init.cache, redirect: init.redirect, signal: init.signal });
      report.requests.push({ method: init.method || 'GET', path: url.pathname, status: res.status,
                             authorization: Boolean(init.headers && init.headers.Authorization) });
      return res;
    };
  },
});
const { document } = dom.window;
await until(() => document.readyState === 'complete' && document.getElementById('btn-save-token'), 15000, 'page load');
report.checks.page_loaded = document.title;

document.getElementById('token-input').value = token;
document.getElementById('btn-save-token').click();
await until(() => /SẴN SÀNG|TOKEN SAI|KHÔNG KẾT NỐI|CHƯA SẴN SÀNG/.test(document.getElementById('service-badge').textContent),
            30000, 'health');
report.checks.service_badge = document.getElementById('service-badge').textContent;
report.checks.health_summary = document.getElementById('health-summary').textContent;

document.querySelector('[data-nav-target=chat]').click();
document.getElementById('chat-general').checked = mode === 'general';
document.getElementById('chat-input').value = question;
document.getElementById('chat-send-btn').click();
const shown = await until(() => document.querySelector('.msg[data-outcome], .msg[data-error]'), 300000, 'chat answer');
report.checks.answer = {
  outcome: shown.getAttribute('data-outcome'),
  error: shown.getAttribute('data-error'),
  text: shown.textContent,
  labels: [...shown.querySelectorAll('.sentence')].map((s) => s.getAttribute('data-label')),
  marks: [...shown.querySelectorAll('.mark')].map((m) => m.textContent),
  meta: (shown.querySelector('.msg-meta') || {}).textContent || null,
};
report.checks.model_panel = JSON.parse(document.getElementById('model-info').textContent || '{}');
report.elapsed_s = (Date.now() - started) / 1000;
report.result = report.checks.service_badge === 'SẴN SÀNG' && report.checks.answer.outcome === 'ANSWERED' ? 'PASS' : 'FAIL';
dom.window.close();
const text = JSON.stringify(report, null, 2);
if (text.includes(token)) throw new Error('refusing to write a report that contains the token');
writeFileSync(outPath, text, { mode: 0o600 });
console.log(JSON.stringify({ result: report.result, outcome: report.checks.answer.outcome,
                             labels: report.checks.answer.labels, elapsed_s: report.elapsed_s }));
process.exit(report.result === 'PASS' ? 0 : 1);
