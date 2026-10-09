import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const source = (await readFile(new URL('../src/api/index.js', import.meta.url), 'utf8'))
  .replace('import.meta.env.VITE_API_BASE_URL', "''");
const { api } = await import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'));
const storage = new Map();
globalThis.localStorage = {
  getItem: key => storage.get(key) ?? null,
  setItem: (key, value) => storage.set(key, value),
  removeItem: key => storage.delete(key),
};

function pending(signal) {
  return new Promise((resolve, reject) => {
    const abort = () => reject(new DOMException('Aborted', 'AbortError'));
    if (signal.aborted) abort();
    else signal.addEventListener('abort', abort, { once: true });
  });
}

test('timeout aborts a stalled request', async () => {
  globalThis.fetch = (url, { signal }) => pending(signal);
  await assert.rejects(api('/test', { timeoutMs: 5 }), error => error.offline && /超时/.test(error.message));
});

test('timeout includes reading a stalled response body', async () => {
  globalThis.fetch = async (url, { signal }) => ({ ok: true, status: 200, json: () => pending(signal) });
  await assert.rejects(api('/test', { timeoutMs: 5 }), /超时/);
});

test('caller cancellation reaches the request', async () => {
  const controller = new AbortController();
  globalThis.fetch = (url, { signal }) => pending(signal);
  const request = api('/test', { signal: controller.signal });
  controller.abort();
  await assert.rejects(request, /超时/);
});

test('successful response keeps credentials and request options', async () => {
  storage.set('token', 'test-token');
  globalThis.fetch = async (url, options) => {
    assert.equal(options.headers.Authorization, 'Bearer test-token');
    assert.equal(options.method, 'POST');
    assert.equal(options.body, '{}');
    assert.ok(options.signal instanceof AbortSignal);
    assert.equal(options.timeoutMs, undefined);
    return { ok: true, status: 200, json: async () => ({ done: true }) };
  };
  assert.deepEqual(await api('/test', { method: 'POST', body: '{}', timeoutMs: 100 }), { done: true });
});

test('empty responses and authentication expiry keep existing behavior', async () => {
  globalThis.fetch = async () => ({ ok: true, status: 204, json: async () => { throw new SyntaxError(); } });
  assert.equal(await api('/test'), null);
  storage.set('active_schedule_id', '1');
  const events = [];
  globalThis.window = { dispatchEvent: event => events.push(event.type) };
  globalThis.fetch = async () => ({ ok: false, status: 401, json: async () => ({ detail: 'expired' }) });
  await assert.rejects(api('/test'), /expired/);
  assert.equal(storage.size, 0);
  assert.deepEqual(events, ['auth:expired']);
});
