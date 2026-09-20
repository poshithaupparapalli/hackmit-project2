// Exercise the actual extension client against the actual FastAPI backend.
// A temporary database and server keep test events/feedback out of the demo DB.
import assert from 'node:assert/strict';
import { spawn, execFileSync } from 'node:child_process';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { resolve } from 'node:path';
import { createServer } from 'node:net';
import { once } from 'node:events';
import { setTimeout as delay } from 'node:timers/promises';
import { createBackend } from '../lib/backend.js';
import { Coordinator } from '../lib/core.js';

const backendDir = resolve(import.meta.dirname, '../../backend');
const python = resolve(backendDir, '.venv/bin/python');
const temp = await mkdtemp(`${tmpdir()}/mia-api-test-`);
const db = `${temp}/test.db`;
const reservation = createServer();
reservation.listen(0, '127.0.0.1'); await once(reservation, 'listening');
const port = reservation.address().port;
await new Promise(resolve => reservation.close(resolve));
const base = `http://127.0.0.1:${port}`;
const server = spawn(python, ['-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', String(port)], {
  cwd: backendDir,
  env: { ...process.env, MIA_DB_PATH: db, DEMO_MODE: 'true', DEMO_LLM: 'false', OPENAI_API_KEY: '' },
  stdio: ['ignore', 'ignore', 'pipe'],
});
server.stderr.resume();
try {
  let healthy = false;
  for (let attempt = 0; attempt < 50; attempt++) {
    try { healthy = (await fetch(`${base}/health`)).ok; } catch { /* starting */ }
    if (healthy) break;
    if (server.exitCode !== null) throw new Error('Test backend failed to start.');
    await delay(100);
  }
  assert.ok(healthy, 'temporary backend started');
  const api = createBackend({ mock: false, backendBaseUrl: base, requestTimeoutMs: 5000 });
  let saved;
  const coordinator = new Coordinator({ api, load: async () => structuredClone(saved), save: async state => { saved = structuredClone(state); } });
  const identity = await coordinator.ensureIdentity();
  await coordinator.observe({ type: 'copy', detail: { length: 6 }, context: { sectionLabel: 'Receipt', targetLabel: 'Total' } }, { url: 'https://mail.google.com/mail/u/0?secret=omitted#omitted', tabId: 1, frameId: 0 });
  await coordinator.observe({ type: 'paste', detail: { targetTag: 'INPUT', targetName: 'total' }, context: { formLabel: 'Expense tracker' } }, { url: 'https://docs.google.com/spreadsheets/d/test', tabId: 2, frameId: 0 });
  const events = structuredClone(saved.queue);
  await coordinator.flush();
  assert.equal(saved.queue.length, 0, 'backend accepted extension events, including omitted clipboard counts');
  assert.ok(saved.lastFlushAt);
  await api.analyze(identity);
  const beforeRetry = await (await fetch(`${base}/v1/status`)).json();
  const repeated = await api.batch(identity, { schemaVersion: 1, installId: identity.installId, sentAt: Date.now(), events });
  assert.deepEqual(repeated.accepted, events.map(event => event.id));
  const afterRetry = await (await fetch(`${base}/v1/status`)).json();
  assert.equal(afterRetry.newEventsPending, beforeRetry.newEventsPending, 'retry does not duplicate stored events');
  const suggestions = await api.suggestions(identity);
  assert.ok(suggestions.length, 'temporary backend demo seed yields a real stored suggestion');
  const id = suggestions[0].id;
  await api.feedback(identity, id, { decision: 'edit', userEdits: 'Only reimbursement receipts.' });
  await api.feedback(identity, id, { decision: 'dismiss' });
  assert.equal((await api.suggestions(identity)).find(item => item.id === id).status, 'dismissed');
  await api.status(identity, id, 'proposed');
  assert.equal((await api.suggestions(identity)).find(item => item.id === id).status, 'proposed');
  await api.feedback(identity, id, { decision: 'accept' });
  assert.equal((await api.suggestions(identity)).find(item => item.id === id).status, 'accepted');
  const feedback = JSON.parse(execFileSync(python, ['-c', 'import sqlite3,json,sys; c=sqlite3.connect(sys.argv[1]); print(json.dumps(c.execute("SELECT decision,user_edits FROM suggestion_feedback ORDER BY id").fetchall()))', db], { encoding: 'utf8' }));
  assert.deepEqual(feedback, [['edit', 'Only reimbursement receipts.'], ['dismiss', null], ['accept', null]]);
  console.log('Live backend integration passed: install/auth, actual extension events, queue acknowledgement, idempotency, suggestions, restore, and persisted Yes/No/Edit.');
} finally {
  if (server.exitCode === null) { const exited = once(server, 'exit'); server.kill('SIGTERM'); await exited; }
  await rm(temp, { recursive: true, force: true });
}
