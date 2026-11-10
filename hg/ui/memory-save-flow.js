/* Behavioral controller for explicit ASK memory saves. Shared by the browser UI and Node tests. */
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.HGMemorySaveFlow = api;
})(typeof window !== 'undefined' ? window : globalThis, function () {
  'use strict';
  const MAX_CONTENT_CHARS = 4000;

  function create(options) {
    if (!options || typeof options.getSnapshot !== 'function'
        || typeof options.requestPreview !== 'function'
        || typeof options.requestSave !== 'function') {
      throw new TypeError('getSnapshot, requestPreview and requestSave are required');
    }
    const onPreview = options.onPreview || function () {};
    const onStatus = options.onStatus || function () {};
    const setBusy = options.setBusy || function () {};
    const onSaved = options.onSaved || function () {};
    const getSnapshot = options.getSnapshot;
    let generation = 0;
    let previewState = null;
    let busy = false;
    let saved = false;

    function currentSnapshot() {
      const value = getSnapshot();
      if (!value || typeof value.subject !== 'string' || typeof value.text !== 'string') return null;
      return { subject: value.subject.trim(), text: value.text.trim() };
    }

    function sameSnapshot(a, b) {
      return Boolean(a && b && a.subject === b.subject && a.text === b.text);
    }

    function invalidate() {
      if (busy || saved) return;
      generation += 1;
      previewState = null;
      onPreview(null, null);
      onStatus('Nội dung thay đổi — cần xem trước lại.');
    }

    async function preview() {
      if (busy || saved) return { status: 'BUSY' };
      const snapshot = currentSnapshot();
      if (!snapshot || !snapshot.subject || !snapshot.text || snapshot.text.length > MAX_CONTENT_CHARS) {
        onStatus('Cần nhập chủ đề và nội dung hợp lệ (tối đa 4000 ký tự).');
        return { status: 'INVALID_INPUT' };
      }
      const requestGeneration = ++generation;
      previewState = null;
      onPreview(null, null);
      setBusy('preview', true);
      onStatus('Đang kiểm tra biên nhận và nội dung…');
      let result;
      try {
        result = await options.requestPreview(snapshot);
      } catch (error) {
        result = { ok: false, status: 0, message: String(error && error.message || error) };
      } finally {
        setBusy('preview', false);
      }
      if (requestGeneration !== generation || !sameSnapshot(snapshot, currentSnapshot())) {
        onStatus('Chủ đề hoặc nội dung đã thay đổi trong lúc xem trước — hãy xem trước lại.');
        return { status: 'STALE_PREVIEW' };
      }
      if (!result || !result.ok || !result.data) {
        onStatus(result && result.status === 0 ? result.message : (options.explain || (r => 'Lỗi HTTP ' + r.status))(result || {}));
        return { status: 'PREVIEW_FAILED', result };
      }
      if (result.data.subject !== snapshot.subject || result.data.content !== snapshot.text
          || typeof result.data.confirmation_sha256 !== 'string') {
        onStatus('Máy chủ trả về bản xem trước không khớp nội dung đã gửi.');
        return { status: 'PREVIEW_MISMATCH' };
      }
      previewState = { snapshot, data: result.data };
      onPreview(result.data, snapshot);
      onStatus('Đọc kỹ toàn bộ bản xem trước. Chỉ xác nhận khi nội dung chính xác.');
      return { status: 'PREVIEW_READY', data: result.data };
    }

    async function confirm() {
      if (busy || saved || !previewState) return { status: 'BUSY_OR_NO_PREVIEW' };
      const snapshot = currentSnapshot();
      if (!sameSnapshot(previewState.snapshot, snapshot)) {
        invalidate();
        return { status: 'STALE_PREVIEW' };
      }
      const payload = {
        subject: previewState.snapshot.subject,
        text: previewState.snapshot.text,
        confirm_sha256: previewState.data.confirmation_sha256
      };
      busy = true;
      setBusy('save', true);
      onStatus('Đang ghi vào sổ ghi chú…');
      let result;
      try {
        result = await options.requestSave(payload);
      } catch (error) {
        result = { ok: false, status: 0, message: String(error && error.message || error) };
      }
      if (!result || result.status === 0 || Number(result.status) >= 500) {
        // The server may have fsync'd the append before the connection/response failed.
        // Keep the exact preview identity; retry is safe because ASK receipt binding is
        // idempotent and an inactive receipt is rejected rather than recreated.
        busy = false;
        setBusy('save', false);
        onStatus('Chưa xác định được kết quả ghi (mất phản hồi hoặc lỗi máy chủ). Ghi nhớ có thể đã được lưu. Giữ nguyên bản xem trước; xác nhận lại sẽ gửi đúng cùng receipt và digest, không tạo bản ghi trùng.');
        return { status: 'SAVE_OUTCOME_UNKNOWN', result };
      }
      if (!result.ok || !result.data || result.data.status !== 'ACTIVE') {
        busy = false;
        setBusy('save', false);
        onStatus((options.explain || (r => 'Lỗi HTTP ' + r.status))(result));
        return { status: 'SAVE_FAILED', result };
      }
      saved = true;
      previewState = null;
      setBusy('saved', true);
      onSaved(result.data, payload);
      onStatus('Đã hoàn tất thao tác lưu có xác nhận.');
      return { status: 'SAVED', data: result.data };
    }

    return {
      invalidate,
      preview,
      confirm,
      getState: function () {
        return { busy, saved, hasPreview: Boolean(previewState), generation };
      },
      MAX_CONTENT_CHARS
    };
  }

  return { create, MAX_CONTENT_CHARS };
});
