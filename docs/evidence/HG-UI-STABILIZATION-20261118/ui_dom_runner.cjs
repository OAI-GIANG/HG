const fs = require('node:fs');
const path = require('node:path');
const { createRequire } = require('node:module');
const requireFromCache = createRequire(path.join(process.env.HG_JSDOM_DIR, 'node_modules', 'shim.js'));
const { JSDOM, VirtualConsole } = requireFromCache('jsdom');
const base = process.argv[2];
const port = Number(JSON.parse(fs.readFileSync(path.join(base, 'server.json'), 'utf8')).port);
const token = fs.readFileSync(path.join(base, 'token.txt'), 'utf8');
const origin = 'http://127.0.0.1:' + port;
const report = { checks: {}, requests: [], console: [] };
const vc = new VirtualConsole();
vc.on('jsdomError', (e) => report.console.push({type:'jsdomError', text:String(e.message)}));
vc.on('error', (m) => report.console.push({type:'error', text:String(m)}));
vc.on('warn', (m) => report.console.push({type:'warn', text:String(m)}));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function until(fn, label, ms=8000) {
  const end=Date.now()+ms;
  while(Date.now()<end) { const v=fn(); if(v) return v; await sleep(50); }
  throw new Error('timeout: '+label);
}
(async()=>{
  const dom=await JSDOM.fromURL(origin+'/ui/', {
    runScripts:'dangerously', resources:'usable', pretendToBeVisual:true, virtualConsole:vc,
    beforeParse(window) {
      window.fetch=async(input,init={})=>{
        const url=new URL(String(input),window.location.href);
        if(url.origin!==origin) throw new Error('cross-origin request refused');
        const res=await globalThis.fetch(url,{method:init.method,headers:init.headers,body:init.body,redirect:init.redirect||'error'});
        report.requests.push({method:init.method||'GET',path:url.pathname,status:res.status,
                              hasAuthorization:Boolean(init.headers&&init.headers.Authorization)});
        return res;
      };
    }
  });
  const d=dom.window.document;
  await until(()=>d.readyState==='complete' && d.getElementById('btn-save-token'),'page load');
  report.checks.page_loaded=d.title;
  d.getElementById('token-input').value=token;
  d.getElementById('btn-save-token').click();
  await until(()=>d.getElementById('service-badge').textContent==='SẴN SÀNG','authenticated ready');
  report.checks.authenticated_ready=d.getElementById('health-summary').textContent;

  d.querySelector('#bottom-nav [data-root-nav=tools]').click();
  d.querySelector('[data-nav-target=models]').click();
  await until(()=>d.getElementById('model-summary').textContent.includes('qwen3:1.7b'),'model status');
  report.checks.model_panel={
    badge:d.getElementById('model-status').textContent,
    summary:d.getElementById('model-summary').textContent,
    data:d.getElementById('model-info').textContent
  };

  d.querySelector('#bottom-nav [data-root-nav=files]').click();
  d.querySelector('[data-nav-target=memory]').click();
  await until(()=>d.getElementById('notes-output').textContent.includes('3.000 km'),'notes list');
  report.checks.notes_rendered=d.getElementById('notes-output').textContent;
  report.checks.xss_not_executed=d.querySelectorAll('#notes-output img').length===0;

  d.querySelector('#bottom-nav [data-root-nav=tools]').click();
  d.querySelector('[data-nav-target=search]').click();
  d.getElementById('search-notes-input').value='thay dầu';
  d.getElementById('btn-search-notes').click();
  await until(()=>d.getElementById('search-output').textContent.includes('3.000 km'),'note search');
  report.checks.search_rendered=d.getElementById('search-output').textContent;

  d.querySelector('[data-nav-target=tools]').click();
  d.getElementById('btn-load-tools').click();
  await until(()=>d.getElementById('tools-output').textContent.includes('fs.write'),'tool registry');
  report.checks.tool_registry=d.getElementById('tools-output').textContent;

  d.getElementById('avatar-settings-btn').click();
  d.getElementById('btn-forget-token').click();
  report.checks.forget_token_clears_sensitive_views =
    d.getElementById('search-output').textContent.includes('Cần kết nối lại') &&
    d.getElementById('notes-count').textContent==='Chưa tải ghi chú.' &&
    d.getElementById('tools-output').textContent.includes('Cần kết nối lại');

  report.checks.all_calls_same_origin=report.requests.every(r=>r.status===200);
  report.checks.expected_routes=[
    '/v1/health/ready','/v1/model','/v1/notes','/v1/notes/search','/v1/tools'
  ].every(p=>report.requests.some(r=>r.path===p));
  report.checks.no_chat_or_inference_route=
    !report.requests.some(r=>r.path==='/v1/chat');
  report.result=Object.values(report.checks).every(v=>{
    if(typeof v==='boolean') return v;
    return true;
  })?'PASS':'FAIL';
  fs.writeFileSync(path.join(base,'ui-dom-report.json'),JSON.stringify(report,null,2),{mode:0o600});
  console.log(JSON.stringify({result:report.result,checks:report.checks,requests:report.requests}));
  dom.window.close();
  process.exit(report.result==='PASS'?0:1);
})().catch(e=>{console.error(e.stack||e);process.exit(1);});
