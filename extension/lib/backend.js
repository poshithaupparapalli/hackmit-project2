export function createBackend(config, storage) {
  async function request(path, { identity, method = 'GET', body } = {}) {
    const url = new URL(config.backendBaseUrl);
    if (url.protocol !== 'https:' && !(url.protocol === 'http:' && ['localhost', '127.0.0.1', '[::1]'].includes(url.hostname))) throw new Error('Use HTTPS for a remote backend.');
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), config.requestTimeoutMs);
    try {
      const response = await fetch(`${config.backendBaseUrl.replace(/\/$/, '')}${path}`, {
        method, signal: controller.signal, cache: 'no-store', credentials: 'omit', redirect: 'error',
        headers: { ...(body ? { 'Content-Type': 'application/json' } : {}), ...(identity ? { Authorization: `Bearer ${identity.installToken}` } : {}) },
        ...(body ? { body: JSON.stringify(body) } : {}),
      });
      if (!response.ok) {
        const error = new Error(`Backend HTTP ${response.status}`);
        error.safeMessage = `Backend returned HTTP ${response.status}. Please retry later.`;
        throw error;
      }
      if (response.status === 204) return null;
      const text = await response.text();
      return text ? JSON.parse(text) : null;
    } finally { clearTimeout(timeout); }
  }
  async function mockSuggestions() {
    return storage.transaction(state => {
      state.mockSuggestions ||= [{
        id: 'mia-demo-receipts', kind: 'workflow', title: 'Log receipt totals to your expense sheet',
        summary: 'Demo proposal: collect receipt totals in your expense tracker.',
        evidence: ['Sample evidence: the receipt workflow was repeated 4 times.'],
        steps: ['Open a receipt email', 'Identify the total', 'Open the expense tracker', 'Add the receipt'],
        trigger: 'A receipt arrives', action: 'Append a receipt to the expense sheet', buildPrompt: '',
        workflowKey: 'gmail_to_sheet', confidence: 0.87, timeSavedPerWeekMinutes: 20,
        status: 'proposed', createdAt: Date.now(), updatedAt: Date.now(),
      }];
      return structuredClone(state.mockSuggestions);
    });
  }
  return {
    install: () => config.mock ? Promise.resolve({ installId: crypto.randomUUID(), installToken: `mock-${crypto.randomUUID()}` }) : request('/v1/install', { method: 'POST' }),
    batch: (identity, body) => config.mock ? Promise.resolve({ accepted: body.events.map(event => event.id), rejected: [], serverTime: Date.now() }) : request('/v1/events/batch', { identity, method: 'POST', body }),
    analyze: identity => config.mock ? Promise.resolve({ queued: true }) : request('/v1/analyze', { identity, method: 'POST', body: {} }),
    async suggestions(identity) {
      if (config.mock) return mockSuggestions();
      const data = await request('/v1/suggestions', { identity });
      // The frozen contract does not specify an envelope. Accept either common
      // representation without changing individual Suggestion field names.
      const list = Array.isArray(data) ? data : data?.suggestions;
      if (!Array.isArray(list)) throw new Error('Invalid suggestions response.');
      return list;
    },
    async feedback(identity, id, body) {
      if (!config.mock) return request(`/v1/suggestions/${encodeURIComponent(id)}/feedback`, { identity, method: 'POST', body });
      await mockSuggestions();
      return storage.transaction(state => {
        const suggestion = state.mockSuggestions.find(item => item.id === id);
        if (!suggestion) throw new Error('Suggestion no longer exists.');
        suggestion.status = body.decision === 'accept' ? 'accepted' : body.decision === 'dismiss' ? 'dismissed' : suggestion.status;
        suggestion.updatedAt = Date.now();
        state.mockFeedback = [...(state.mockFeedback || []), { id, ...body }].slice(-50);
      });
    },
    async status(identity, id, status) {
      if (!config.mock) return request(`/v1/suggestions/${encodeURIComponent(id)}`, { identity, method: 'PATCH', body: { status } });
      await mockSuggestions();
      return storage.transaction(state => {
        const suggestion = state.mockSuggestions.find(item => item.id === id);
        if (suggestion) { suggestion.status = status; suggestion.updatedAt = Date.now(); }
      });
    },
  };
}
