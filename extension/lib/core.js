import './privacy.js';
const P = globalThis.MiaPrivacy;
export const DEFAULT_SETTINGS = Object.freeze({ paused: false, excludedDomains: ['accounts.google.com', 'login.microsoftonline.com'], windowDays: 7, minNewEvents: 25, analyzeEveryMinutes: 30 });
export const LIMITS = Object.freeze({ count: 5000, bytes: 5_000_000, batch: 250, immediate: 100, sessionMs: 15 * 60 * 1000 });
export const serializedBytes = value => new TextEncoder().encode(JSON.stringify(value)).length;
export function freshState() {
  return { settings: structuredClone(DEFAULT_SETTINGS), identity: null, queue: [], pending: [], recent: [], sequence: 0, sessionId: null, lastEventAt: null, retryAt: 0, failures: 0, dropped: 0, lastFlushAt: null, lastError: null, rejected: [], tabs: {}, mockSuggestions: null, lastAnalyzeRequestAt: 0 };
}

// Every storage read/modify/write is serialized. Network requests are outside
// this lock so observation and pause stay responsive during backend downtime.
export class Coordinator {
  constructor({ load, save, api, now = Date.now, uuid = () => crypto.randomUUID(), limits = LIMITS }) {
    Object.assign(this, { load, save, api, now, uuid, limits });
    this.chain = Promise.resolve();
    this.flushing = null;
    this.installing = null;
  }
  transaction(fn) {
    const task = this.chain.then(async () => {
      const state = (await this.load()) || freshState();
      const result = await fn(state);
      await this.save(state);
      return result;
    });
    this.chain = task.catch(() => {});
    return task;
  }
  snapshot() {
    const task = this.chain.then(async () => structuredClone((await this.load()) || freshState()));
    this.chain = task.catch(() => {});
    return task;
  }
  async setSettings(patch) {
    return this.transaction(state => {
      if (typeof patch.paused === 'boolean') state.settings.paused = patch.paused;
      if (Array.isArray(patch.excludedDomains)) {
        const domains = patch.excludedDomains.map(P.normalizeDomain);
        if (domains.some(domain => !domain) || domains.length > 100) {
          const error = new Error('Invalid domains');
          error.safeMessage = 'Enter a website domain without a path (maximum 100 websites).';
          throw error;
        }
        state.settings.excludedDomains = [...new Set(domains)];
      }
      // Stop retaining tab metadata for sites newly excluded, or while paused.
      for (const [id, tab] of Object.entries(state.tabs)) {
        if (state.settings.paused || P.isExcludedDomain(tab.host, state.settings.excludedDomains)) delete state.tabs[id];
      }
      return structuredClone(state.settings);
    });
  }
  ensureIdentity() {
    if (this.installing) return this.installing;
    this.installing = this._ensureIdentity().finally(() => { this.installing = null; });
    return this.installing;
  }
  async _ensureIdentity() {
    const existing = await this.transaction(state => state.identity);
    if (existing) return existing;
    const identity = await this.api.install();
    if (!identity || typeof identity.installId !== 'string' || !identity.installId || identity.installId.length > 128 || typeof identity.installToken !== 'string' || !identity.installToken) throw new Error('Invalid installation response.');
    return this.transaction(state => {
      state.identity ||= { installId: identity.installId, installToken: identity.installToken };
      state.queue.push(...state.pending.map(event => ({ ...event, installId: state.identity.installId })));
      state.pending = [];
      // Reserved identity overhead during offline staging keeps this within limits.
      return state.identity;
    });
  }
  async observe(raw, source) {
    return this.transaction(state => {
      const url = P.sanitizeUrl(source.url);
      const top = P.sanitizeUrl(source.topUrl || source.url);
      if (source.incognito || state.settings.paused || !url || !top || P.isExcludedDomain(url.host, state.settings.excludedDomains) || P.isExcludedDomain(top.host, state.settings.excludedDomains)) return false;
      const observation = P.sanitizeObservation(raw);
      if (!observation || !Number.isInteger(source.tabId) || !Number.isInteger(source.frameId)) return false;
      const now = this.now();
      const sessionId = !state.sessionId || state.lastEventAt === null || now - state.lastEventAt >= LIMITS.sessionMs ? this.uuid() : state.sessionId;
      const event = { schemaVersion: 1, id: this.uuid(), sessionId, timestamp: now, sequence: state.sequence + 1, tabId: source.tabId, frameId: source.frameId, ...url, ...observation };
      const title = P.sanitizeContextText(source.title, 160);
      if (title) event.title = title;
      if (state.identity) event.installId = state.identity.installId;
      const proposed = [...state.queue, ...state.pending, event];
      const bytes = serializedBytes(proposed) + (state.pending.length + (state.identity ? 0 : 1)) * 512;
      if (proposed.length > this.limits.count || bytes > this.limits.bytes) { state.dropped++; return false; }
      state.sequence = event.sequence;
      state.sessionId = sessionId;
      state.lastEventAt = now;
      (state.identity ? state.queue : state.pending).push(event);
      state.recent = [...state.recent, event].slice(-40);
      if (source.frameId === 0 && observation.type !== 'tabclose') state.tabs[source.tabId] = { ...url };
      return true;
    });
  }
  flush() {
    if (this.flushing) return this.flushing;
    this.flushing = this._flush().finally(() => { this.flushing = null; });
    return this.flushing;
  }
  async _flush() {
    const initial = await this.snapshot();
    if (this.now() < initial.retryAt) return;
    try {
      const identity = await this.ensureIdentity();
      const batch = await this.transaction(state => state.queue.slice(0, this.limits.batch));
      if (!batch.length) return;
      const response = await this.api.batch(identity, { schemaVersion: 1, installId: identity.installId, sentAt: this.now(), events: batch });
      if (!response || !Array.isArray(response.accepted) || !response.accepted.every(id => typeof id === 'string') || !Array.isArray(response.rejected) || !Number.isFinite(response.serverTime)) throw new Error('Invalid batch acknowledgement. Events retained.');
      const sent = new Set(batch.map(event => event.id));
      const accepted = new Set(response.accepted.filter(id => sent.has(id)));
      let requestAnalysis = false;
      await this.transaction(state => {
        state.queue = state.queue.filter(event => !accepted.has(event.id));
        // Do not store backend free-text errors: they might echo event contents.
        state.rejected = response.rejected.filter(item => sent.has(item.id)).slice(0, 50).map(item => ({ id: item.id, reason: 'Backend rejected event; retained for retry.' }));
        if (accepted.size) {
          state.lastFlushAt = this.now(); state.failures = 0; state.retryAt = 0;
          state.lastError = state.rejected.length ? 'Some events were rejected and remain queued.' : null;
          if (this.now() - (state.lastAnalyzeRequestAt || 0) >= 60_000) {
            state.lastAnalyzeRequestAt = this.now();
            requestAnalysis = true;
          }
        } else this.recordFailure(state, 'No events acknowledged. Events retained.');
      });
      // Ingestion and analysis are separate contract seams. Requesting an
      // analysis after an acknowledged batch makes the live demo responsive;
      // the backend owns gating, deduplication and expensive LLM work.
      if (requestAnalysis && this.api.analyze) {
        try { await this.api.analyze(identity); } catch { /* ingestion already succeeded */ }
      }
    } catch (error) {
      await this.transaction(state => this.recordFailure(state, error.safeMessage || 'Backend unavailable. Events remain on this device.'));
    }
  }
  recordFailure(state, message) {
    state.failures++;
    state.retryAt = this.now() + Math.min(30 * 60 * 1000, 30000 * 2 ** Math.min(state.failures - 1, 6));
    state.lastError = message;
  }
}
