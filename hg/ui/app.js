/* HG web UI, served by hg serve at /ui/ (docs/architecture/HG_SERVICE_V1.md §5, revision 2026-10-29).
 *
 * - Every call goes to the origin that served this page (relative paths under /v1/), so the page
 *   talks to exactly the hg-runtime listener it came from: no hard-coded host or port.
 * - The service token is typed or pasted by the owner, kept in this tab only (sessionStorage),
 *   and sent only as an Authorization header. Never in persistent web storage, never in the URL.
 * - All text from the service is rendered with textContent (no HTML injection sinks).
 */
(function () {
  'use strict';

  const TOKEN_KEY = 'hg.runtime.token';
  const CHAT_TIMEOUT_MS = 300000;
  const TASK_ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/;
  const navStack = ['home'];
  let token = '';

  const $ = (id) => document.getElementById(id);
  const screens = {};
  ['home', 'chat', 'models', 'memory', 'files', 'tools', 'tasks', 'search', 'diagnostics', 'settings']
    .forEach((key) => { screens[key] = $('screen-' + key); });

  const screenTitleEl = $('screen-title');
  const backBtn = $('back-btn');
  const bottomNav = $('bottom-nav');
  const serviceBadge = $('service-badge');
  const toastEl = $('global-toast');
  const chatMessagesEl = $('chat-messages');
  const chatInputEl = $('chat-input');
  const chatSendBtn = $('chat-send-btn');
  const chatGeneralEl = $('chat-general');
  const tokenInputEl = $('token-input');
  const tokenStatusEl = $('token-status');

  // ---------- small helpers ----------

  function showToast(msg, isError) {
    toastEl.textContent = msg;
    toastEl.classList.toggle('error', Boolean(isError));
    toastEl.hidden = false;
  }

  function hideToast() {
    toastEl.hidden = true;
    toastEl.textContent = '';
  }

  function setBadge(el, text, kind) {
    el.textContent = text;
    el.className = 'badge badge-' + kind;
  }

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }

  function shortDate(iso) {
    const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso || '');
    return m ? m[3] + '/' + m[2] : '?';
  }

  const ERROR_TEXT = {
    unauthorized: 'Token sai hoặc thiếu (401). Vào Kết nối, dán đúng token của hg-runtime.',
    invalid_host: 'Địa chỉ trang không phải loopback của dịch vụ (400).',
    chat_busy: 'HG đang trả lời một tin nhắn khác. Chờ xong rồi gửi lại.',
    chat_unavailable: 'Dịch vụ này chưa bật chat.',
    assistant_unavailable: 'Thư mục trợ lý (HG_HOME) không dùng được. Trong Termux chạy: hg note list',
    assistant_busy: 'Một lệnh hg khác đang dùng ghi chú. Thử lại sau vài giây.',
    model_untrusted: 'Model local bị từ chối (tiến trình hoặc digest không khớp). Trong Termux chạy: hg model status',
    notes_ledger_damaged: 'Sổ ghi chú không đọc được. Trong Termux chạy: hg repair',
    service_not_ready: 'Dịch vụ chưa sẵn sàng: bản phát hành chưa được xác minh.',
    invalid_message: 'Tin nhắn trống hoặc dài quá 2000 ký tự.',
    invalid_request: 'Yêu cầu không đúng định dạng.',
    body_too_large: 'Tin nhắn quá lớn.',
    not_found: 'Không tìm thấy.',
    task_not_found: 'Không có tác vụ với mã này.',
    internal_error: 'Dịch vụ gặp lỗi nội bộ.'
  };

  function explain(result) {
    const code = result && result.data && result.data.error;
    const known = code && ERROR_TEXT[code];
    return (known || ('Lỗi HTTP ' + result.status)) + (code ? ' [' + code + ']' : '');
  }

  // ---------- token (this tab only) ----------

  function loadToken() {
    try {
      token = window.sessionStorage.getItem(TOKEN_KEY) || '';
    } catch (_e) {
      token = '';
    }
    tokenStatusEl.textContent = token ? 'Đã có token trong tab này.' : 'Chưa có token.';
  }

  function validToken(value) {
    return /^[\x21-\x7e]{32,}$/.test(value);
  }

  function saveToken(value) {
    token = value;
    try {
      window.sessionStorage.setItem(TOKEN_KEY, value);
    } catch (_e) {
      // Storage refused (private mode): keep the token in memory for this page only.
    }
  }

  function forgetToken() {
    token = '';
    try {
      window.sessionStorage.removeItem(TOKEN_KEY);
    } catch (_e) {
      // nothing stored
    }
    tokenInputEl.value = '';
    tokenStatusEl.textContent = 'Đã quên token.';
    setBadge(serviceBadge, 'CHƯA KIỂM TRA', 'neutral');
  }

  // ---------- one request to the service that served this page ----------

  async function api(method, path, body, timeoutMs) {
    if (!token) {
      return { status: 0, ok: false, data: { error: 'no_token' }, message: 'Chưa có token: vào Kết nối để dán token.' };
    }
    const headers = {};
    headers['Authorization'] = 'Bearer ' + token;
    const init = { method: method, headers: headers, cache: 'no-store', credentials: 'omit',
                   redirect: 'error', referrerPolicy: 'no-referrer' };
    if (body !== undefined) {
      headers['Content-Type'] = 'application/json';
      init.body = JSON.stringify(body);
    }
    let timer = null;
    if (timeoutMs) {
      const controller = new AbortController();
      init.signal = controller.signal;
      timer = setTimeout(() => controller.abort(), timeoutMs);
    }
    try {
      const res = await fetch(path, init);
      const text = await res.text();
      let data = null;
      try {
        data = JSON.parse(text);
      } catch (_e) {
        data = null;
      }
      return { status: res.status, ok: res.ok, data: data };
    } catch (err) {
      const aborted = err && err.name === 'AbortError';
      return { status: 0, ok: false, data: { error: aborted ? 'timeout' : 'network' },
               message: aborted ? 'Hết thời gian chờ câu trả lời.' : 'Không kết nối được hg-runtime (dịch vụ có đang chạy?).' };
    } finally {
      if (timer) clearTimeout(timer);
    }
  }

  // ---------- navigation ----------

  function navigateTo(screenKey, pushHistory) {
    const target = screens[screenKey];
    if (!target) return;
    Object.values(screens).forEach((s) => s.classList.remove('active'));
    target.classList.add('active');
    if (pushHistory !== false && navStack[navStack.length - 1] !== screenKey) navStack.push(screenKey);
    screenTitleEl.textContent = target.getAttribute('data-title') || screenKey;
    backBtn.hidden = navStack.length <= 1;
    bottomNav.classList.toggle('hidden', target.getAttribute('data-hide-bottom-nav') === 'true');
    const activeRoot = target.getAttribute('data-root');
    document.querySelectorAll('[data-root-nav]').forEach((btn) => {
      btn.classList.toggle('active', btn.getAttribute('data-root-nav') === activeRoot);
    });
  }

  backBtn.addEventListener('click', () => {
    if (navStack.length > 1) {
      navStack.pop();
      navigateTo(navStack[navStack.length - 1], false);
    }
  });
  $('avatar-settings-btn').addEventListener('click', () => navigateTo('settings'));
  document.querySelectorAll('[data-nav-target]').forEach((btn) => {
    btn.addEventListener('click', () => navigateTo(btn.getAttribute('data-nav-target')));
  });

  // ---------- health ----------

  async function probeHealth() {
    const summaryEl = $('health-summary');
    const diagEl = $('diag-health-status');
    const jsonEl = $('diag-health-json');
    const result = await api('GET', '/v1/health/ready');
    if (result.status === 0) {
      summaryEl.textContent = result.message;
      setBadge(serviceBadge, result.data.error === 'no_token' ? 'CHƯA CÓ TOKEN' : 'KHÔNG KẾT NỐI', 'offline');
      setBadge(diagEl, serviceBadge.textContent, 'offline');
      return false;
    }
    jsonEl.textContent = JSON.stringify(result.data, null, 2);
    if (result.status === 200 && result.data && result.data.status === 'READY') {
      const rid = String(result.data.release_id || '').slice(0, 12);
      summaryEl.textContent = 'Dịch vụ SẴN SÀNG · bản phát hành ' + rid + '… · toàn vẹn ' +
        result.data.integrity + ' · quyền ' + result.data.trust;
      setBadge(serviceBadge, 'SẴN SÀNG', 'online');
      setBadge(diagEl, 'READY (HTTP 200)', 'online');
      hideToast();
      return true;
    }
    const text = result.status === 401 ? explain(result)
      : 'Dịch vụ CHƯA SẴN SÀNG (HTTP ' + result.status + ')';
    summaryEl.textContent = text;
    setBadge(serviceBadge, result.status === 401 ? 'TOKEN SAI' : 'CHƯA SẴN SÀNG', 'offline');
    setBadge(diagEl, 'HTTP ' + result.status, 'offline');
    return false;
  }

  $('btn-probe-health').addEventListener('click', probeHealth);

  $('btn-save-token').addEventListener('click', async () => {
    const value = tokenInputEl.value.trim();
    if (!validToken(value)) {
      tokenStatusEl.textContent = 'Token phải có ít nhất 32 ký tự ASCII in được, không có khoảng trắng.';
      return;
    }
    saveToken(value);
    tokenInputEl.value = '';
    tokenStatusEl.textContent = 'Đang kiểm tra token…';
    const ok = await probeHealth();
    tokenStatusEl.textContent = ok ? 'Token đúng, dịch vụ sẵn sàng.' : $('health-summary').textContent;
  });
  $('btn-forget-token').addEventListener('click', forgetToken);

  // ---------- chat ----------

  function appendMessage(role, className) {
    const wrapper = el('div', 'msg' + (className ? ' ' + className : ''));
    const header = el('div', 'msg-header');
    header.appendChild(el('strong', null, role));
    const body = el('div', 'msg-body');
    wrapper.appendChild(header);
    wrapper.appendChild(body);
    chatMessagesEl.appendChild(wrapper);
    chatMessagesEl.scrollTop = chatMessagesEl.scrollHeight;
    return { wrapper: wrapper, header: header, body: body };
  }

  function markFor(sentence, notesByRef) {
    if (sentence.label === 'NOTE') {
      const note = notesByRef[sentence.note];
      return '[' + sentence.note + '·' + shortDate(note && note.created_at) + ']';
    }
    if (sentence.label === 'MODEL') return '[?]';
    if (sentence.label === 'CONFLICT') return '[≠' + sentence.note + ']';
    if (sentence.label === 'BADCITE') return '[!]';
    return '';
  }

  function renderAnswer(data) {
    const view = appendMessage('HG');
    view.wrapper.setAttribute('data-outcome', String(data.outcome));
    const notesByRef = {};
    (data.notes || []).forEach((n) => { notesByRef[n.ref] = n; });
    (data.note_conflicts || []).forEach((c) => {
      view.body.appendChild(el('span', 'reason', '⚠ ' + c.notes.join(' và ') + ' nói khác nhau: ' + (c.reasons || []).join('; ')));
    });
    if (data.sentences && data.sentences.length) {
      data.sentences.forEach((s) => {
        const line = el('span', 'sentence');
        line.setAttribute('data-label', String(s.label));
        line.appendChild(document.createTextNode(s.sentence));
        const mark = markFor(s, notesByRef);
        if (mark) line.appendChild(el('span', 'mark mark-' + s.label, mark));
        view.body.appendChild(line);
        if ((s.label === 'CONFLICT' || s.label === 'BADCITE') && s.reasons && s.reasons.length) {
          view.body.appendChild(el('span', 'reason', '↳ ' + s.reasons.join('; ')));
        }
      });
    } else if (data.outcome === 'MEMORY_ONLY') {
      view.body.appendChild(el('span', 'sentence', 'Không có model' + (data.error ? ' (' + data.error + ')' : '') +
        ': HG chỉ đưa nguyên văn ghi chú bên dưới, không tự viết câu trả lời.'));
    } else {
      view.body.appendChild(el('span', 'sentence', data.answer || ('HG không có ghi chú nào về câu hỏi này' +
        (data.error ? ' và không có model (' + data.error + ').' : '.'))));
    }
    (data.notes || []).forEach((n) => {
      view.body.appendChild(el('span', 'note-item', n.ref + ' (' + shortDate(n.created_at) + '): ' +
        (n.content === null ? '[ghi chú đã đổi sau khi trả lời]' : n.content)));
    });
    if (data.quarantined && data.quarantined.length) {
      view.body.appendChild(el('span', 'note-item', '⚠ ' + data.quarantined.length +
        ' ghi chú chứa câu lệnh nhắm vào AI — không gửi cho model.'));
    }
    const counts = data.counts || {};
    const parts = [data.outcome];
    if (data.provider) parts.push(data.provider + ':' + data.model);
    if (typeof data.seconds === 'number') parts.push(data.seconds.toFixed(1) + ' giây');
    if (data.counts) parts.push((counts.NOTE || 0) + ' câu có nguồn · ' + (counts.MODEL || 0) + ' câu model tự nói');
    const brain = data.brain || {};
    if (brain.receipt_event_id) parts.push('biên nhận ' + String(brain.receipt_event_id).slice(0, 8));
    view.wrapper.appendChild(el('div', 'msg-meta', parts.join(' · ')));
    renderModelInfo(data);
  }

  function renderModelInfo(data) {
    const brain = data.brain || {};
    $('model-info').textContent = JSON.stringify({
      provider: data.provider, model: data.model, model_check: data.model_check, listener: data.listener,
      router: brain.router, provider_policy: brain.provider_policy, model_calls: brain.model_calls,
      release: data.release
    }, null, 2);
  }

  async function sendChat() {
    const raw = chatInputEl.value;
    if (!raw || raw.trim().length === 0) {
      showToast('Không gửi tin nhắn trống.', true);
      return;
    }
    if (!token) {
      showToast('Chưa có token: vào Kết nối để dán token.', true);
      navigateTo('settings');
      return;
    }
    hideToast();
    const mine = appendMessage('Chủ Nhân', 'msg-user');
    mine.body.textContent = raw.trim();
    chatInputEl.value = '';
    chatSendBtn.disabled = true;
    const pending = appendMessage('HG');
    pending.wrapper.setAttribute('data-pending', 'true');
    pending.body.textContent = 'HG đang trả lời… (model chạy trên điện thoại, có thể mất 10–60 giây)';
    const result = await api('POST', '/v1/chat', { message: raw.trim(), general: Boolean(chatGeneralEl.checked) },
                             CHAT_TIMEOUT_MS);
    pending.wrapper.remove();
    chatSendBtn.disabled = false;
    if (result.ok && result.data) {
      renderAnswer(result.data);
      return;
    }
    const failure = appendMessage('HG — lỗi', 'msg-error');
    failure.wrapper.setAttribute('data-error', String((result.data && result.data.error) || result.status));
    failure.body.textContent = result.status === 0 ? result.message : explain(result);
  }

  // Enter inserts a newline in the textarea; only the Send button sends.
  chatInputEl.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') e.stopPropagation();
  });
  chatSendBtn.addEventListener('click', sendChat);

  // ---------- tasks ----------

  $('btn-fetch-tasks').addEventListener('click', async () => {
    const outEl = $('tasks-output');
    const id = $('task-scope-id').value.trim();
    if (!TASK_ID.test(id)) {
      outEl.textContent = 'Mã tác vụ: 1–128 ký tự chữ, số và . _ : - (bắt đầu bằng chữ hoặc số).';
      return;
    }
    const result = await api('GET', '/v1/tasks/' + id);
    outEl.textContent = result.status === 0 ? result.message
      : (result.ok ? JSON.stringify(result.data, null, 2) : explain(result));
  });

  loadToken();
  if (token) probeHealth();
})();
