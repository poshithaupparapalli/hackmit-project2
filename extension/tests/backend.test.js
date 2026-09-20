import test from 'node:test';
import assert from 'node:assert/strict';
import { createBackend } from '../lib/backend.js';
const config = { mock: false, backendBaseUrl: 'https://mia.example', requestTimeoutMs: 1000 };
const identity = { installId: 'id', installToken: 'TOKEN_ONLY_IN_AUTH_HEADER' };
test('real client preserves frozen endpoint and feedback shapes', async () => {
  const originalFetch = globalThis.fetch, calls = [];
  globalThis.fetch = async (url, options) => {
    calls.push({ url, options });
    return new Response(JSON.stringify(url.endsWith('/install') ? identity : url.endsWith('/suggestions') ? [] : {}), { status: 200 });
  };
  try {
    const api = createBackend(config);
    await api.install();
    await api.batch(identity, { schemaVersion: 1, installId: 'id', sentAt: 1, events: [] });
    await api.analyze(identity);
    await api.suggestions(identity);
    await api.feedback(identity, 'a/b', { decision: 'edit', userEdits: 'Only reimbursement receipts.' });
    await api.status(identity, 'a/b', 'proposed');
    assert.deepEqual(calls.map(call => call.url), ['https://mia.example/v1/install', 'https://mia.example/v1/events/batch', 'https://mia.example/v1/analyze', 'https://mia.example/v1/suggestions', 'https://mia.example/v1/suggestions/a%2Fb/feedback', 'https://mia.example/v1/suggestions/a%2Fb']);
    assert.equal(calls[0].options.body, undefined);
    assert.equal(calls[0].options.headers.Authorization, undefined);
    assert.equal(calls[1].options.headers.Authorization, 'Bearer TOKEN_ONLY_IN_AUTH_HEADER');
    assert.equal(calls[1].options.body.includes('TOKEN_ONLY_IN_AUTH_HEADER'), false);
    assert.deepEqual(JSON.parse(calls[4].options.body), { decision: 'edit', userEdits: 'Only reimbursement receipts.' });
    assert.deepEqual(JSON.parse(calls[5].options.body), { status: 'proposed' });
    assert.equal(calls[5].options.method, 'PATCH');
  } finally { globalThis.fetch = originalFetch; }
});
test('feedback accepts 204; error body never becomes a surfaced error; redirects disabled', async () => {
  const originalFetch = globalThis.fetch;
  try {
    globalThis.fetch = async (_url, options) => { assert.equal(options.redirect, 'error'); return new Response(null, { status: 204 }); };
    const api = createBackend(config);
    assert.equal(await api.feedback(identity, 'id', { decision: 'accept' }), null);
    globalThis.fetch = async () => new Response('PRIVATE_RESPONSE_TEXT', { status: 503 });
    await assert.rejects(api.suggestions(identity), error => error.safeMessage.includes('503') && !error.message.includes('PRIVATE'));
    await assert.rejects(createBackend({ ...config, backendBaseUrl: 'http://remote.example' }).install(), /HTTPS/);
  } finally { globalThis.fetch = originalFetch; }
});
