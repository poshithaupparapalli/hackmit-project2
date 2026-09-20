// Optional real-browser smoke test. Requires Playwright and a Chrome executable.
// Uses an isolated temporary profile; never attaches to the user's own browser.
import { createRequire } from 'node:module';
import { mkdtemp, readFile, rm, cp, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { resolve } from 'node:path';
import { createServer } from 'node:http';
import assert from 'node:assert/strict';
const require = createRequire(import.meta.url);
const { chromium } = require(process.env.MIA_PLAYWRIGHT_PATH || 'playwright');
const root = resolve(import.meta.dirname, '..');
const profile = await mkdtemp(`${tmpdir()}/mia-browser-`);
// Keep this UI/observation smoke test deterministic even when the actual
// unpacked extension is configured for the live backend.
const testExtension = `${profile}/test-extension`;
await cp(root, testExtension, { recursive: true, filter: path => !path.includes('/node_modules') && !path.includes('/tests') });
await writeFile(`${testExtension}/config.js`, 'export const CONFIG = { mock: true, backendBaseUrl: "http://localhost:8000", debug: true, requestTimeoutMs: 15000 };\n');
const server = createServer(async (request, response) => {
  const file = new URL(request.url, 'http://localhost').pathname === '/expenses.html' ? 'expenses.html' : 'receipt.html';
  response.setHeader('Content-Type', 'text/html'); response.end(await readFile(`${root}/fixtures/${file}`));
});
await new Promise(resolve => server.listen(8765, '0.0.0.0', resolve));
let context;
const launchOptions = {
    executablePath: process.env.MIA_CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    headless: true,
    ignoreDefaultArgs: ['--disable-extensions'],
    args: ['--enable-unsafe-extension-debugging'],
  };
try {
  context = await chromium.launchPersistentContext(profile, launchOptions);
  const cdp = await context.browser().newBrowserCDPSession();
  await cdp.send('Extensions.loadUnpacked', { path: testExtension });
  let worker = context.serviceWorkers()[0] || await context.waitForEvent('serviceworker', { timeout: 15000 });
  const extensionId = new URL(worker.url()).host;
  let panel = await context.newPage();
  await panel.setViewportSize({ width: 380, height: 850 });
  panel.on('pageerror', error => console.error('Panel error:', error.message));
  await panel.goto(`chrome-extension://${extensionId}/sidepanel.html`);
  await panel.getByText('Mia is observing', { exact: true }).waitFor({ timeout: 5000 }).catch(async error => {
    console.error('Panel status:', await panel.locator('body').innerText());
    console.error('Worker init:', await worker.evaluate(async () => { try { await chrome.storage.local.setAccessLevel({ accessLevel: 'TRUSTED_CONTEXTS' }); return Object.keys(await chrome.storage.local.get(null)); } catch (error) { return error.message; } }));
    throw error;
  });
  await panel.getByRole('heading', { name: 'Log receipt totals to your expense sheet' }).waitFor();
  const readState = () => worker.evaluate(async () => Object.values(await chrome.storage.local.get(null))[0]);
  const page = await context.newPage();
  await page.goto('http://localhost:8765/receipt.html?private=SECRET_QUERY#SECRET_FRAGMENT');
  await page.locator('#receipt').click();
  await page.waitForTimeout(200);
  let state = await readState();
  assert.ok(state.recent.some(event => event.type === 'click' && event.context?.targetLabel?.includes('receipt')));
  const beforePassword = state.sequence;
  await page.locator('#password').click(); await page.locator('#password').fill('SECRET_PASSWORD');
  await page.locator('#password').press('ControlOrMeta+c'); await page.waitForTimeout(1000);
  assert.equal((await readState()).sequence, beforePassword, 'password actions create zero events');
  // Select the number by a DOM Range without reading its text.
  await page.locator('#amount').click();
  await page.evaluate(() => { document.activeElement.blur(); const range = document.createRange(); range.selectNodeContents(document.querySelector('#amount').firstChild); const selection = getSelection(); selection.removeAllRanges(); selection.addRange(range); });
  await page.keyboard.press('ControlOrMeta+c');
  await page.waitForTimeout(200);
  const copied = (await readState()).recent.find(event => event.type === 'copy' && event.context?.targetLabel?.toLowerCase() === 'total');
  assert.ok(copied);
  assert.equal(copied.context.pageTitle, 'Mia receipt rehearsal');
  assert.equal(copied.context.itemTitle, 'Receipt rehearsal');
  assert.equal(copied.context.semanticType, 'currency');
  const sheet = await context.newPage(); await sheet.goto('http://127.0.0.1:8765/expenses.html');
  await sheet.locator('#total').click(); await sheet.keyboard.press('ControlOrMeta+v');
  await sheet.locator('#note').fill('SECRET_EMAIL_BODY'); await sheet.locator('#row').fill('SECRET_SHEET_ROW');
  await sheet.getByRole('button', { name: 'Add row' }).click(); await sheet.waitForTimeout(1000);
  state = await readState();
  const pasted = state.recent.find(event => event.type === 'paste' && event.context?.targetLabel?.toLowerCase() === 'total');
  assert.ok(pasted);
  assert.equal(pasted.context.pageTitle, 'Expense tracker');
  assert.equal(pasted.context.formLabel, 'Add expense');
  assert.equal(pasted.context.semanticType, 'currency');
  for (const type of ['copy', 'paste', 'edit', 'submit', 'nav']) assert.ok(state.recent.some(event => event.type === type), `recorded ${type}`);
  const trace = JSON.stringify({ queue: state.queue, recent: state.recent });
  for (const secret of ['42.18', 'SECRET_PASSWORD', 'SECRET_EMAIL_BODY', 'SECRET_SHEET_ROW', 'SECRET_QUERY', 'SECRET_FRAGMENT']) assert.equal(trace.includes(secret), false, `trace excludes ${secret}`);
  await panel.getByRole('button', { name: 'Pause', exact: true }).click(); await panel.getByText('Mia is paused', { exact: true }).waitFor();
  const pausedAt = (await readState()).sequence;
  await sheet.locator('#total').fill('123456'); await sheet.getByRole('button', { name: 'Add row' }).click(); await sheet.waitForTimeout(1000);
  assert.equal((await readState()).sequence, pausedAt);
  await panel.getByRole('button', { name: 'Resume', exact: true }).click(); await panel.getByText('Mia is observing', { exact: true }).waitFor();
  await panel.locator('#domain').fill('127.0.0.1'); await panel.getByRole('button', { name: 'Add', exact: true }).click();
  await panel.getByRole('button', { name: 'Stop excluding 127.0.0.1' }).waitFor();
  const excludedAt = (await readState()).sequence;
  await sheet.locator('#total').fill('private'); await sheet.getByRole('button', { name: 'Add row' }).click(); await sheet.waitForTimeout(1000); await sheet.close(); await page.waitForTimeout(200);
  assert.equal((await readState()).sequence, excludedAt);
  await panel.getByRole('button', { name: 'I have edits', exact: true }).click(); await panel.locator('textarea').fill('Only reimbursement receipts over $25.'); await panel.getByRole('button', { name: 'Save correction' }).click();
  await panel.getByText('Your correction was saved for future analysis.').waitFor();
  assert.equal((await readState()).mockFeedback.at(-1).userEdits, 'Only reimbursement receipts over $25.');
  await panel.getByRole('button', { name: 'No', exact: true }).click(); await panel.getByRole('button', { name: 'Restore' }).click(); await panel.getByRole('button', { name: 'Yes', exact: true }).click();
  await panel.getByText('Accepted · ready for your next decision').waitFor();
  assert.equal((await readState()).mockSuggestions[0].status, 'accepted');
  const beforeReload = await readState();
  await context.close();
  context = await chromium.launchPersistentContext(profile, launchOptions);
  const restartCdp = await context.browser().newBrowserCDPSession();
  await restartCdp.send('Extensions.loadUnpacked', { path: testExtension });
  panel = await context.newPage();
  await panel.setViewportSize({ width: 380, height: 850 });
  await panel.goto(`chrome-extension://${extensionId}/sidepanel.html`);
  await panel.getByText('Accepted · ready for your next decision').waitFor();
  worker = context.serviceWorkers()[0] || await context.waitForEvent('serviceworker', { timeout: 15000 });
  const afterReload = await readState();
  assert.equal(afterReload.identity.installId, beforeReload.identity.installId);
  assert.equal(afterReload.sequence, beforeReload.sequence);
  assert.deepEqual(afterReload.recent.map(event => event.id), beforeReload.recent.map(event => event.id));
  await panel.evaluate(() => window.scrollTo(0, 0));
  await panel.screenshot({ path: `${root}/tests/panel-smoke.png`, fullPage: true });
  assert.ok(await panel.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'panel fits 380px');
  console.log('Real Chrome smoke passed: MV3 boot, content→storage, receipt workflow privacy, pause, exclusion, feedback, and persisted identity/history after browser restart.');
} finally {
  await context?.close(); server.close(); await rm(profile, { recursive: true, force: true });
}
