(() => {
  const token = '__FIXTURE_TOKEN__';
  const checks = {};
  const fetchAPI = window.fetch.bind(window);
  const select = (s) => document.querySelector(s);
  const click = (s) => select(s).click();
  const text = (s) => select(s).textContent;
  const sleep = (ms) => new Promise(resolve => setTimeout(resolve, ms));
  let violations = 0;
  document.addEventListener('securitypolicyviolation', () => violations++);
  async function wait(fn) {
    for (let i = 0; i < 150; i++) {
      if (fn()) return true;
      await sleep(80);
    }
    return false;
  }
  async function run() {
    let failure = null;
    try {
      checks.android_chrome = /Android.+Chrome\//.test(navigator.userAgent) &&
        !/EdgA|SamsungBrowser|; wv\)/.test(navigator.userAgent);
      checks.usable_viewport = window.innerWidth > 0 &&
        document.documentElement.scrollWidth <= window.innerWidth + 1;
      click('#avatar-settings-btn');
      select('#token-input').value = token;
      click('#btn-save-token');
      checks.connected = await wait(() => text('#service-badge').includes('SẴN SÀNG'));
      click('#bottom-nav [data-root-nav=chat]');
      select('#chat-general').checked = false;
      select('#chat-input').value = 'Lần cuối thay dầu xe\nkhi nào?';
      click('#chat-send-btn');
      await wait(() => !!select('.msg[data-outcome]'));
      const answer = select('.msg[data-outcome] .sentence[data-label=NOTE]');
      checks.note_label = !!answer && answer.textContent.includes('18.200');
      checks.multiline_submitted = text('.msg-user .msg-body').includes('\n');
      if (answer) {
        const range = document.createRange();
        range.selectNodeContents(answer);
        const selection = window.getSelection();
        selection.removeAllRanges();
        selection.addRange(range);
        checks.text_selectable = selection.toString().includes('18.200');
        selection.removeAllRanges();
      } else {
        checks.text_selectable = false;
      }
      window.fetch = async (input, options) => {
        if (input === '/v1/chat') throw new TypeError('synthetic connection loss');
        return fetchAPI(input, options);
      };
      select('#chat-input').value = 'Kiểm tra mất kết nối';
      click('#chat-send-btn');
      checks.failure_visible = await wait(() => !!select('.msg-error[data-error=network]'));
      checks.no_url_token = !location.href.includes(token) &&
        performance.getEntriesByType('resource').every(e => !e.name.includes(token));
      checks.no_csp_violation = violations === 0;
    } catch (error) {
      failure = String(error.name);
    } finally {
      window.fetch = fetchAPI;
      sessionStorage.clear();
    }
    const r = await fetchAPI('/ui/phase1-result', {
      method: 'POST', headers: { 'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json' },
      body: JSON.stringify({ checks, failure })
    });
    const note = document.createElement('p');
    note.textContent = r.ok && Object.values(checks).every(x => x === true) && !failure ?
      'HG staging — kiểm tra tự động hoàn tất.' : 'HG staging — cần xem log kiểm tra.';
    document.body.prepend(note);
  }
  if (document.readyState === 'complete') run();
  else window.addEventListener('load', run, { once: true });
})();
