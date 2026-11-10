'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { create, MAX_CONTENT_CHARS } = require('../ui/memory-save-flow.js');

function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

function harness(overrides = {}) {
  const state = { subject: 'bao-duong-xe', text: 'Một trích đoạn nguyên văn từ câu trả lời.' };
  const calls = { preview: [], save: [], busy: [], status: [], rendered: [] };
  const controls = { subjectDisabled: false, contentDisabled: false,
    previewDisabled: false, confirmDisabled: false };
  const flow = create({
    getSnapshot: () => ({ ...state }),
    requestPreview: async snapshot => {
      calls.preview.push(snapshot);
      if (overrides.requestPreview) return overrides.requestPreview(snapshot);
      return { ok: true, status: 200, data: {
        subject: snapshot.subject, content: snapshot.text, confirmation_sha256: 'd'.repeat(64)
      }};
    },
    requestSave: async payload => {
      calls.save.push(payload);
      if (overrides.requestSave) return overrides.requestSave(payload);
      return { ok: true, status: 200, data: { status: 'ACTIVE', created: true, memory_id: 'M-1' } };
    },
    setBusy: (phase, value) => {
      calls.busy.push([phase, value]);
      if (phase === 'preview') controls.previewDisabled = value;
      if (phase === 'save' || phase === 'saved') {
        const disabled = value || phase === 'saved';
        controls.subjectDisabled = disabled;
        controls.contentDisabled = disabled;
        controls.previewDisabled = disabled;
        controls.confirmDisabled = disabled;
      }
    },
    onStatus: message => calls.status.push(message),
    onPreview: (preview, snapshot) => calls.rendered.push([preview, snapshot]),
    onSaved: data => calls.saved = data,
  });
  return { state, calls, controls, flow };
}

test('delayed preview is discarded after content changes and invalidation', async () => {
  const wait = deferred();
  const h = harness({ requestPreview: () => wait.promise });
  const pending = h.flow.preview();
  h.state.text = 'Nội dung đã thay đổi';
  h.flow.invalidate();
  wait.resolve({ ok: true, status: 200, data: {
    subject: 'bao-duong-xe', content: 'Một trích đoạn nguyên văn từ câu trả lời.',
    confirmation_sha256: 'd'.repeat(64)
  }});
  assert.equal((await pending).status, 'STALE_PREVIEW');
  assert.equal(h.flow.getState().hasPreview, false);
});

test('delayed preview is discarded after subject changes', async () => {
  const wait = deferred();
  const h = harness({ requestPreview: () => wait.promise });
  const pending = h.flow.preview();
  h.state.subject = 'chu-de-khac';
  h.flow.invalidate();
  wait.resolve({ ok: true, status: 200, data: {
    subject: 'bao-duong-xe', content: h.state.text, confirmation_sha256: 'e'.repeat(64)
  }});
  assert.equal((await pending).status, 'STALE_PREVIEW');
  assert.equal(h.flow.getState().hasPreview, false);
});

test('stale subject/content cannot submit an old confirmation digest', async () => {
  const h = harness();
  assert.equal((await h.flow.preview()).status, 'PREVIEW_READY');
  h.state.subject = 'chu-de-bi-sua';
  assert.equal((await h.flow.confirm()).status, 'STALE_PREVIEW');
  assert.equal(h.calls.save.length, 0);
  assert.equal(h.flow.getState().hasPreview, false);
});

test('inputs are locked during save and unlocked after a failed save', async () => {
  const wait = deferred();
  const h = harness({ requestSave: () => wait.promise });
  await h.flow.preview();
  const pending = h.flow.confirm();
  assert.deepEqual(h.calls.busy.slice(-1)[0], ['save', true]);
  assert.equal(h.flow.getState().busy, true);
  assert.deepEqual(h.controls, { subjectDisabled: true, contentDisabled: true,
    previewDisabled: true, confirmDisabled: true });
  wait.resolve({ ok: false, status: 409, data: { error: 'memory_conflict' } });
  assert.equal((await pending).status, 'SAVE_FAILED');
  assert.deepEqual(h.calls.busy.slice(-1)[0], ['save', false]);
  assert.equal(h.flow.getState().busy, false);
  assert.deepEqual(h.controls, { subjectDisabled: false, contentDisabled: false,
    previewDisabled: false, confirmDisabled: false });
  assert.equal(h.flow.getState().hasPreview, true);
});

test('concurrent/double confirmation sends exactly one save request', async () => {
  const wait = deferred();
  const h = harness({ requestSave: () => wait.promise });
  await h.flow.preview();
  const first = h.flow.confirm();
  const second = await h.flow.confirm();
  assert.equal(second.status, 'BUSY_OR_NO_PREVIEW');
  assert.equal(h.calls.save.length, 1);
  wait.resolve({ ok: true, status: 200, data: { status: 'ACTIVE', created: true, memory_id: 'M-9' } });
  assert.equal((await first).status, 'SAVED');
  assert.equal(h.flow.getState().saved, true);
  assert.deepEqual(h.controls, { subjectDisabled: true, contentDisabled: true,
    previewDisabled: true, confirmDisabled: true });
  assert.equal(h.calls.saved.memory_id, 'M-9');
});


test('lost save response is OUTCOME_UNKNOWN and exact retry does not duplicate the record', async () => {
  let persisted = null;
  let attempts = 0;
  const h = harness({
    requestSave: async payload => {
      attempts += 1;
      if (!persisted) persisted = { memory_id: 'M-unknown', payload: { ...payload } };
      if (attempts === 1) {
        // Simulate: durable append committed, but the HTTP response was lost.
        return { ok: false, status: 0, data: { error: 'timeout' }, message: 'response lost' };
      }
      assert.deepEqual(payload, persisted.payload);
      return { ok: true, status: 200, data: {
        status: 'ACTIVE', created: false, memory_id: persisted.memory_id
      }};
    }
  });
  await h.flow.preview();
  const first = await h.flow.confirm();
  assert.equal(first.status, 'SAVE_OUTCOME_UNKNOWN');
  assert.equal(h.flow.getState().busy, false);
  assert.equal(h.flow.getState().hasPreview, true);
  assert.equal(h.flow.getState().saved, false);
  assert.match(h.calls.status.at(-1), /Chưa xác định được kết quả ghi/);
  const second = await h.flow.confirm();
  assert.equal(second.status, 'SAVED');
  assert.equal(second.data.created, false);
  assert.equal(second.data.memory_id, 'M-unknown');
  assert.equal(attempts, 2);
  assert.ok(persisted);
  assert.equal(h.flow.getState().saved, true);
});

test('HTTP 5xx after save submission is treated as an unknown outcome', async () => {
  const h = harness({ requestSave: async () => ({
    ok: false, status: 503, data: { error: 'notes_ledger_damaged' }
  })});
  await h.flow.preview();
  assert.equal((await h.flow.confirm()).status, 'SAVE_OUTCOME_UNKNOWN');
  assert.equal(h.flow.getState().hasPreview, true);
  assert.equal(h.flow.getState().busy, false);
});

test('4,000 characters are allowed and 4,001 are rejected before preview request', async () => {
  const h = harness();
  assert.equal(MAX_CONTENT_CHARS, 4000);
  h.state.text = 'x'.repeat(4000);
  assert.equal((await h.flow.preview()).status, 'PREVIEW_READY');
  assert.equal(h.calls.preview.length, 1);
  h.state.text = 'x'.repeat(4001);
  assert.equal((await h.flow.preview()).status, 'INVALID_INPUT');
  assert.equal(h.calls.preview.length, 1);
});

test('preview server response must match submitted subject and content', async () => {
  const h = harness({ requestPreview: async () => ({ ok: true, status: 200, data: {
    subject: 'other', content: 'other', confirmation_sha256: 'f'.repeat(64)
  }}) });
  assert.equal((await h.flow.preview()).status, 'PREVIEW_MISMATCH');
  assert.equal(h.flow.getState().hasPreview, false);
});
