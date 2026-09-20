/**
 * Typed client for the two backend processes the dashboard talks to:
 *   - Kathy's detection API (suggestions)   default http://localhost:8000
 *   - Poshitha's agent (execution + OAuth)  default http://localhost:8010
 * Override with VITE_MIA_BACKEND_URL / VITE_MIA_AGENT_URL for a non-local run.
 */

export const BACKEND_URL = (import.meta.env.VITE_MIA_BACKEND_URL as string | undefined) ?? 'http://localhost:8000';
export const AGENT_URL = (import.meta.env.VITE_MIA_AGENT_URL as string | undefined) ?? 'http://localhost:8010';

export type SuggestionKind = 'workflow' | 'automation' | 'rule';
export type SuggestionStatus = 'proposed' | 'accepted' | 'dismissed' | 'built';

export interface Suggestion {
  id: string;
  kind: SuggestionKind;
  title: string;
  summary: string;
  evidence: string[];
  steps: string[];
  trigger: string;
  action: string;
  buildPrompt: string;
  workflowKey: string | null;
  confidence: number;
  timeSavedPerWeekMinutes: number;
  status: SuggestionStatus;
  createdAt: number;
  updatedAt: number;
}

export type RunStatus = 'running' | 'done' | 'error' | 'needs_approval';
export type StepState = 'pending' | 'running' | 'done' | 'error';

export interface RunStep {
  label: string;
  state: StepState;
}

export interface ApprovalRequest {
  title: string;
  description: string;
}

export interface WorkflowRun {
  runId: string;
  workflowKey: string;
  status: RunStatus;
  steps: RunStep[];
  result: Record<string, unknown> | null;
  error: string | null;
  approvalRequest: ApprovalRequest | null;
  suggestionId: string | null;
  startedAt: number | null;
  triggeredBy: 'manual' | 'auto';
}

export interface GoogleAuthStatus {
  configured: boolean;
  connected: boolean;
}

export interface ChatMessage {
  role: 'user' | 'mia';
  content: string;
  createdAt: number;
}

export interface ChatResponse {
  reply: ChatMessage;
  messages: ChatMessage[];
}

async function asJson<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const detail = await res.text().catch(() => '');
    let message = detail;
    try {
      const parsed = JSON.parse(detail);
      message = typeof parsed?.detail === 'string' ? parsed.detail : detail;
    } catch {
      /* not JSON — use raw text */
    }
    throw new Error(message || `HTTP ${res.status}`);
  }
  if (res.status === 204) return null as T;
  return res.json() as Promise<T>;
}

/** Kathy's detection API — suggestions live here. */
export const backend = {
  listSuggestions(): Promise<Suggestion[]> {
    return fetch(`${BACKEND_URL}/v1/suggestions`).then((r) => asJson<Suggestion[]>(r));
  },
  setStatus(id: string, status: SuggestionStatus): Promise<Suggestion> {
    return fetch(`${BACKEND_URL}/v1/suggestions/${encodeURIComponent(id)}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ status }),
    }).then((r) => asJson<Suggestion>(r));
  },
  feedback(id: string, decision: 'accept' | 'dismiss' | 'edit', userEdits?: string): Promise<{ ok: boolean }> {
    return fetch(`${BACKEND_URL}/v1/suggestions/${encodeURIComponent(id)}/feedback`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ decision, ...(userEdits ? { userEdits } : {}) }),
    }).then((r) => asJson<{ ok: boolean }>(r));
  },
  getChat(id: string): Promise<ChatMessage[]> {
    return fetch(`${BACKEND_URL}/v1/suggestions/${encodeURIComponent(id)}/chat`).then((r) => asJson<ChatMessage[]>(r));
  },
  sendChatMessage(id: string, message: string): Promise<ChatResponse> {
    return fetch(`${BACKEND_URL}/v1/suggestions/${encodeURIComponent(id)}/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message }),
    }).then((r) => asJson<ChatResponse>(r));
  },
};

/** Poshitha's agent — execution + the Google OAuth web flow. */
export const agent = {
  authStatus(): Promise<GoogleAuthStatus> {
    return fetch(`${AGENT_URL}/v1/auth/google/status`).then((r) => asJson<GoogleAuthStatus>(r));
  },
  authStartUrl(): string {
    return `${AGENT_URL}/v1/auth/google/start`;
  },
  runWorkflow(workflowKey: string, suggestionId: string): Promise<{ runId: string }> {
    return fetch(`${AGENT_URL}/v1/workflows/${encodeURIComponent(workflowKey)}/run`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ suggestionId }),
    }).then((r) => asJson<{ runId: string }>(r));
  },
  getRun(runId: string): Promise<WorkflowRun> {
    return fetch(`${AGENT_URL}/v1/workflows/runs/${encodeURIComponent(runId)}`).then((r) => asJson<WorkflowRun>(r));
  },
  listRuns(limit = 50): Promise<WorkflowRun[]> {
    return fetch(`${AGENT_URL}/v1/workflows/runs?limit=${limit}`).then((r) => asJson<WorkflowRun[]>(r));
  },
  approveRun(runId: string, decision: 'approve' | 'cancel'): Promise<WorkflowRun> {
    return fetch(`${AGENT_URL}/v1/workflows/runs/${encodeURIComponent(runId)}/approve?decision=${decision}`, {
      method: 'POST',
    }).then((r) => asJson<WorkflowRun>(r));
  },
};

/** Human-readable names for the fixed set of executable workflows (B7 registry). */
export const WORKFLOW_LABELS: Record<string, string> = {
  gmail_to_sheet: 'Gmail → Sheets',
  email_to_calendar: 'Email → Calendar',
};

export function workflowLabel(key: string | null): string {
  if (!key) return 'Not yet automatable';
  return WORKFLOW_LABELS[key] ?? key;
}
