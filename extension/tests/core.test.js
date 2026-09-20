import test from 'node:test';
import assert from 'node:assert/strict';
import { Coordinator, freshState, LIMITS, serializedBytes } from '../lib/core.js';
const P = globalThis.MiaPrivacy;
const source = { url: 'https://mail.google.com/mail/u/0?q=secret#private', tabId: 7, frameId: 0 };
const click = { type: 'click', detail: { tag: 'BUTTON', label: 'Save $42.18 person@example.com', value: 'SECRET' }, context: { sectionLabel: 'Receipt' } };
function harness(options = {}) {
  let stored, now = 1000000, counter = 0;
  const api = { install: async () => ({ installId: 'install-id', installToken: 'secret-token' }), batch: async (_identity, body) => ({ accepted: body.events.map(event => event.id), rejected: [], serverTime: now }), ...options.api };
  const dependencies = { load: async () => structuredClone(stored), save: async value => { stored = structuredClone(value); }, api, now: () => now, uuid: () => `uuid-${++counter}`, ...options };
  const make = () => new Coordinator(dependencies);
  return { coordinator: make(), make, api, advance: ms => { now += ms; }, state: () => stored };
}
test('privacy drops unknown fields, values, password metadata, URL query/fragment', () => {
  assert.deepEqual(P.sanitizeUrl(source.url), { host: 'mail.google.com', path: '/mail/u/0' });
  assert.equal(P.sanitizeUrl('chrome://settings'), null);
  assert.equal(P.sanitizeObservation({ type: 'edit', detail: { inputType: 'password', length: 8 } }), null);
  const clean = P.sanitizeObservation(click);
  assert.equal(clean.detail.label, 'Save $42.18 person@example.com');
  assert.equal(clean.detail.value, undefined);
  assert.equal(P.sanitizeObservation({ type: '__proto__' }), null);
  assert.ok(serializedBytes(clean.detail) < 2048);
  assert.equal(P.sanitizeText('Receipt from Uber — Sep 19'), 'Receipt from Uber — Sep 19');
  assert.equal(P.sanitizeContextText('Authorization: Bearer abcdefghijklmnop'), '');
  assert.equal(P.sanitizeContextText('SECRET_EMAIL_BODY'), '');
  const rich = P.sanitizeObservation({ type: 'copy', context: {
    pageTitle: 'Gmail', itemTitle: 'Receipt from Uber', sectionLabel: 'September',
    targetLabel: 'Total', nearbyText: 'Receipt from Uber — Sep 19', semanticType: 'currency',
  }});
  assert.deepEqual(rich.context, {
    pageTitle: 'Gmail', itemTitle: 'Receipt from Uber', sectionLabel: 'September',
    targetLabel: 'Total', nearbyText: 'Receipt from Uber — Sep 19', semanticType: 'currency',
  });
  assert.equal(P.sanitizeObservation({ type: 'copy', context: { itemTitle: 'Card 4111 1111 1111 1111' } }).context, undefined);
});
test('exclusions match subdomains, not lookalikes; domains normalized', () => {
  assert.ok(P.isExcludedDomain('foo.accounts.google.com', ['accounts.google.com']));
  assert.equal(P.isExcludedDomain('notaccounts.google.com', ['accounts.google.com']), false);
  assert.equal(P.normalizeDomain('https://Example.com/'), 'example.com');
  assert.equal(P.normalizeDomain('example.com/private'), null);
});
test('pause, excluded frames/top-level pages and incognito create zero events', async () => {
  const { coordinator: c } = harness();
  await c.setSettings({ paused: true });
  assert.equal(await c.observe(click, source), false);
  await c.setSettings({ paused: false });
  assert.equal(await c.observe(click, { ...source, url: 'https://accounts.google.com/login' }), false);
  assert.equal(await c.observe(click, { ...source, topUrl: 'https://accounts.google.com' }), false);
  assert.equal(await c.observe(click, { ...source, incognito: true }), false);
  assert.equal((await c.snapshot()).pending.length, 0);
});
test('offline first launch stages safe events durably, then attaches real identity', async () => {
  const h = harness({ api: { install: async () => { throw Error('offline'); } } });
  await h.coordinator.observe(click, source);
  await h.coordinator.flush();
  assert.equal(h.state().pending.length, 1);
  const restarted = h.make();
  h.api.install = async () => ({ installId: 'real-id', installToken: 'secret' });
  // Constructor api override is the same instance used by dependencies.
  restarted.api.install = h.api.install;
  await restarted.ensureIdentity();
  const state = await restarted.snapshot();
  assert.equal(state.pending.length, 0);
  assert.equal(state.queue[0].installId, 'real-id');
  assert.equal(state.queue[0].sequence, 1);
  assert.equal(JSON.stringify(state.queue).includes('SECRET'), false);
});
test('sequence/session persist across restart, session renews after 15 minutes', async () => {
  const h = harness();
  await h.coordinator.ensureIdentity();
  await Promise.all(Array.from({ length: 20 }, () => h.coordinator.observe(click, source)));
  const initial = await h.coordinator.snapshot();
  assert.deepEqual(initial.queue.map(event => event.sequence), Array.from({ length: 20 }, (_, i) => i + 1));
  h.advance(LIMITS.sessionMs);
  const restarted = h.make(); await restarted.observe(click, source);
  const state = await restarted.snapshot();
  assert.equal(state.queue.at(-1).sequence, 21);
  assert.notEqual(state.queue.at(-1).sessionId, initial.sessionId);
});
test('concurrent flush is single-flight; only accepted submitted IDs removed, new events survive', async () => {
  let resolveBatch, calls = 0, submitted;
  const h = harness();
  h.coordinator.api.batch = async (_id, body) => { calls++; submitted = body.events; return new Promise(resolve => { resolveBatch = resolve; }); };
  await h.coordinator.ensureIdentity();
  await h.coordinator.observe(click, source); await h.coordinator.observe(click, source);
  const a = h.coordinator.flush(), b = h.coordinator.flush();
  while (!resolveBatch) await new Promise(resolve => setImmediate(resolve));
  await h.coordinator.observe(click, source);
  const newId = h.state().queue.at(-1).id;
  resolveBatch({ accepted: [submitted[0].id, newId], rejected: [{ id: submitted[1].id, reason: 'private text' }], serverTime: 1 });
  await Promise.all([a, b]);
  assert.equal(calls, 1);
  assert.deepEqual(h.state().queue.map(event => event.id), [submitted[1].id, newId]);
  assert.equal(JSON.stringify(h.state().rejected).includes('private text'), false);
});
test('network failure persists exponential retry; alarm before retry does not resend', async () => {
  const h = harness(); let calls = 0;
  h.coordinator.api.batch = async () => { calls++; throw Error('offline'); };
  await h.coordinator.ensureIdentity(); await h.coordinator.observe(click, source);
  await h.coordinator.flush(); const first = h.state().retryAt;
  await h.make().flush(); assert.equal(calls, 1); assert.equal(h.state().queue.length, 1);
  h.advance(30000); await h.coordinator.flush();
  assert.equal(h.state().retryAt - first, 60000);
});
test('batch caps at 250 and malformed/no acknowledgements never delete events', async () => {
  const h = harness(); await h.coordinator.ensureIdentity();
  for (let i = 0; i < 251; i++) await h.coordinator.observe(click, source);
  let size;
  h.coordinator.api.batch = async (_id, body) => { size = body.events.length; return { accepted: [], rejected: [], serverTime: 1 }; };
  await h.coordinator.flush(); assert.equal(size, 250); assert.equal(h.state().queue.length, 251);
  h.advance(30000); h.coordinator.api.batch = async () => ({ accepted: 'all' });
  await h.coordinator.flush(); assert.equal(h.state().queue.length, 251);
});
test('count and UTF-8 byte limits preserve queued events and report overflow', async () => {
  const h = harness({ limits: { ...LIMITS, count: 2 } });
  await h.coordinator.ensureIdentity();
  await h.coordinator.observe(click, source); await h.coordinator.observe(click, source);
  assert.equal(await h.coordinator.observe(click, source), false);
  assert.equal(h.state().queue.length, 2); assert.equal(h.state().dropped, 1);
  const tiny = harness({ limits: { ...LIMITS, bytes: 100 } });
  assert.equal(await tiny.coordinator.observe(click, source), false);
  assert.equal(tiny.state().pending.length, 0);
  assert.equal(serializedBytes('é'), 4);
});
test('new exclusions invalidate cached tab metadata', async () => {
  const h = harness(); await h.coordinator.observe(click, source);
  await h.coordinator.setSettings({ excludedDomains: ['google.com'] });
  assert.deepEqual(h.state().tabs, {});
  assert.equal(await h.coordinator.observe(click, source), false);
  assert.deepEqual(Object.keys(freshState().settings).sort(), ['analyzeEveryMinutes', 'excludedDomains', 'minNewEvents', 'paused', 'windowDays']);
});
