import { CONFIG } from './config.js';
import { Coordinator, LIMITS } from './lib/core.js';
import { createBackend } from './lib/backend.js';
const P = globalThis.MiaPrivacy;
const STATE_KEY = `mia:${CONFIG.mock ? 'mock' : CONFIG.backendBaseUrl}:v1`;
// Restrict storage BEFORE persisting anything. Content scripts obtain only a
// filtered settings response and never read local storage directly.
const storageReady = chrome.storage.local.setAccessLevel({ accessLevel: 'TRUSTED_CONTEXTS' });
let coordinator;
const backend = createBackend(CONFIG, { transaction: fn => coordinator.transaction(fn) });
coordinator = new Coordinator({
  load: async () => { await storageReady; return (await chrome.storage.local.get(STATE_KEY))[STATE_KEY]; },
  save: async state => { await storageReady; await chrome.storage.local.set({ [STATE_KEY]: state }); },
  api: backend,
});
const safely = promise => promise.catch(() => { /* Never log raw page/server errors. */ });
const isPanel = sender => sender.id === chrome.runtime.id && sender.url === chrome.runtime.getURL('sidepanel.html');
async function publicSettings(sender) {
  const state = await coordinator.snapshot();
  const url = P.sanitizeUrl(sender.tab?.url || sender.url);
  return { settings: state.settings, blocked: !!sender.tab?.incognito || (sender.tab ? !url || P.isExcludedDomain(url.host, state.settings.excludedDomains) : false) };
}
async function broadcastSettings(settings) {
  const tabs = await chrome.tabs.query({});
  await Promise.allSettled(tabs.map(tab => {
    const url = P.sanitizeUrl(tab.url);
    return chrome.tabs.sendMessage(tab.id, { kind: 'settings', settings, blocked: tab.incognito || !url || P.isExcludedDomain(url.host, settings.excludedDomains) });
  }));
}
async function observe(observation, source) {
  const stored = await coordinator.observe(observation, source);
  if (stored) {
    const state = await coordinator.snapshot();
    if (state.queue.length + state.pending.length >= LIMITS.immediate) safely(coordinator.flush());
  }
  return stored;
}
async function handle(message, sender) {
  if (sender.id !== chrome.runtime.id) throw new Error('Unavailable.');
  if (message?.kind === 'settings:get') return publicSettings(sender);
  if (message?.kind === 'observe' && sender.tab && Number.isInteger(sender.frameId)) {
    // Fetch current top-level URL as a second exclusion check for cross-origin
    // frames. IDs and URL come from Chrome, never from the observation payload.
    const tab = await chrome.tabs.get(sender.tab.id);
    return observe(message.observation, { url: sender.url, topUrl: tab.url, title: tab.title || '', tabId: tab.id, frameId: sender.frameId, incognito: tab.incognito });
  }
  if (!isPanel(sender)) throw new Error('Unavailable.');
  if (message.kind === 'panel:state') {
    const state = await coordinator.snapshot();
    return { settings: state.settings, recent: state.recent, queueLength: state.queue.length + state.pending.length, pendingIdentity: !state.identity, dropped: state.dropped, lastFlushAt: state.lastFlushAt, lastAnalyzeRequestAt: state.lastAnalyzeRequestAt, lastError: state.lastError, retryAt: state.retryAt, rejected: state.rejected, mock: CONFIG.mock, debug: CONFIG.debug };
  }
  if (message.kind === 'settings:update') {
    const settings = await coordinator.setSettings(message.patch || {});
    await broadcastSettings(settings);
    return settings;
  }
  if (message.kind === 'queue:flush') {
    await coordinator.flush();
    if (!CONFIG.mock) {
      const state = await coordinator.snapshot();
      if (Date.now() - (state.lastAnalyzeRequestAt || 0) >= 60_000) {
        await coordinator.transaction(current => { current.lastAnalyzeRequestAt = Date.now(); });
        await backend.analyze(await coordinator.ensureIdentity());
      }
    }
    return true;
  }
  if (message.kind === 'suggestions:get') return backend.suggestions(await coordinator.ensureIdentity());
  if (message.kind === 'suggestions:feedback') {
    if (!['accept', 'dismiss', 'edit'].includes(message.decision) || typeof message.id !== 'string') throw new Error('Invalid feedback.');
    const body = { decision: message.decision };
    if (message.decision === 'edit') {
      if (typeof message.userEdits !== 'string' || !message.userEdits.trim() || message.userEdits.length > 2000) throw new Error('Enter a correction, up to 2,000 characters.');
      body.userEdits = message.userEdits.trim();
    }
    await backend.feedback(await coordinator.ensureIdentity(), message.id, body);
    return true;
  }
  if (message.kind === 'suggestions:restore' && typeof message.id === 'string') {
    await backend.status(await coordinator.ensureIdentity(), message.id, 'proposed'); return true;
  }
  throw new Error('Unknown request.');
}
// Register listeners synchronously so Chrome can wake a suspended worker.
chrome.runtime.onMessage.addListener((message, sender, respond) => {
  handle(message, sender).then(data => respond({ ok: true, data })).catch(error => respond({ ok: false, error: error.safeMessage || 'Mia could not complete that request. Please try again.' }));
  return true;
});
async function setup() {
  await storageReady;
  await chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true });
  if (!await chrome.alarms.get('mia-flush')) await chrome.alarms.create('mia-flush', { periodInMinutes: 0.5 });
  await coordinator.flush();
}
chrome.runtime.onInstalled.addListener(() => safely(setup()));
chrome.runtime.onStartup.addListener(() => safely(setup()));
chrome.alarms.onAlarm.addListener(alarm => { if (alarm.name === 'mia-flush') safely(coordinator.flush()); });

async function navigation(details) {
  const tab = await chrome.tabs.get(details.tabId);
  const url = P.sanitizeUrl(details.url);
  if (!url) return;
  const state = await coordinator.snapshot();
  const previous = state.tabs[details.tabId];
  const top = P.sanitizeUrl(tab.url);
  if (details.frameId === 0 && (!top || tab.incognito || state.settings.paused || P.isExcludedDomain(url.host, state.settings.excludedDomains))) {
    await coordinator.transaction(current => { delete current.tabs[tab.id]; });
    return;
  }
  const last = state.recent.at(-1);
  if (last?.type === 'nav' && last.tabId === details.tabId && last.frameId === details.frameId && last.host === url.host && last.path === url.path && Date.now() - last.timestamp < 750) return;
  await observe({ type: 'nav', detail: previous ? { referrerHost: previous.host } : {} }, { url: details.url, topUrl: tab.url, title: tab.title || '', tabId: details.tabId, frameId: details.frameId, incognito: tab.incognito });
  safely(chrome.tabs.sendMessage(tab.id, { kind: 'navigation' }, { frameId: details.frameId }));
}
chrome.webNavigation.onCommitted.addListener(details => safely(navigation(details)));
chrome.webNavigation.onHistoryStateUpdated.addListener(details => safely(navigation(details)));
chrome.webNavigation.onReferenceFragmentUpdated.addListener(details => safely(navigation(details)));
chrome.tabs.onCreated.addListener(tab => {
  if (tab.url || tab.pendingUrl) safely(observe({ type: 'tabopen' }, { url: tab.url || tab.pendingUrl, title: tab.title || '', tabId: tab.id, frameId: 0, incognito: tab.incognito }));
});
chrome.tabs.onUpdated.addListener((tabId, change, tab) => {
  if (!change.url) return;
  safely(coordinator.transaction(state => {
    const url = P.sanitizeUrl(tab.url);
    // Closing an excluded/restricted page must not reuse its previous site's URL.
    if (!url || tab.incognito || P.isExcludedDomain(url.host, state.settings.excludedDomains)) delete state.tabs[tabId];
  }));
});
chrome.tabs.onRemoved.addListener(tabId => safely((async () => {
  const state = await coordinator.snapshot();
  const previous = state.tabs[tabId];
  if (previous) await observe({ type: 'tabclose' }, { url: `https://${previous.host}${previous.path}`, tabId, frameId: 0 });
  await coordinator.transaction(current => { delete current.tabs[tabId]; });
})()));
// Focus is observed in content.js to suppress it when a password is focused.
// Periodic alarm registration is also repaired when any event wakes the worker.
safely(setup());
