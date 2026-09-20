/**
 * MIA dashboard — the "workflows app" the extension's side panel points to.
 * Accepting/dismissing a proposal already happens in the side panel; running
 * a workflow (the one action Mia never takes on her own) happens here.
 *
 * Talks to two independent local processes:
 *   - Kathy's detection backend (suggestions)   see src/lib/api.ts BACKEND_URL
 *   - Poshitha's agent (execution + OAuth)      see src/lib/api.ts AGENT_URL
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { MiaAvatar } from './components/mia/MiaAvatar';
import type { MiaState } from './components/mia/mia-personality';
import {
  AGENT_URL,
  BACKEND_URL,
  agent,
  backend,
  workflowLabel,
  type ChatMessage,
  type GoogleAuthStatus,
  type PendingTrigger,
  type RunMode,
  type Suggestion,
  type SuggestionKind,
  type WorkflowRun,
} from './lib/api';
import './dashboard.css';

const POLL_MS = 4000;

function errMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

function relativeTime(ms: number | null | undefined): string {
  if (!ms) return '';
  const deltaS = Math.round((Date.now() - ms) / 1000);
  if (deltaS < 5) return 'just now';
  if (deltaS < 60) return `${deltaS}s ago`;
  const deltaM = Math.round(deltaS / 60);
  if (deltaM < 60) return `${deltaM}m ago`;
  const deltaH = Math.round(deltaM / 60);
  if (deltaH < 24) return `${deltaH}h ago`;
  return new Date(ms).toLocaleDateString();
}

// The analyst sometimes numbers its own step text ("1. Open the email...");
// the <ol> numbers it too. Strip a redundant leading "1." / "1)" so a step
// never shows up double-numbered.
function stripLeadingNumber(text: string): string {
  return text.replace(/^\s*\d+[.)]\s+/, '');
}

// What each kind actually means for the person deciding: workflow/automation
// are concrete actions Mia can perform for you; a rule is a standing
// preference she'll remember, with no "run" of its own (nothing in the agent
// today can check a rule's condition, so offering Run on one would be
// misleading — see backend/app/analyst.py _determine_workflow_key).
const KIND_INFO: Record<SuggestionKind, { label: string; blurb: string }> = {
  workflow: { label: 'Workflow', blurb: 'A repeatable task Mia can do for you, on demand.' },
  automation: { label: 'Automation', blurb: 'A single action Mia can do for you, on demand.' },
  rule: { label: 'Rule', blurb: "A preference Mia will remember — not something you run." },
};

function confidencePct(value: number): string {
  return `${Math.round(Math.max(0, Math.min(1, value)) * 100)}%`;
}

/** Suggestions/runs the person hasn't decided about yet still count as "idle". */
function overallMiaState(suggestions: Suggestion[], runs: WorkflowRun[]): MiaState {
  if (runs.some((r) => r.status === 'needs_approval')) return 'confirming';
  if (runs.some((r) => r.status === 'running')) return 'running';
  if (suggestions.some((s) => s.status === 'proposed')) return 'suggesting';
  return 'idle';
}

function RunProgress({ run }: { run: WorkflowRun }) {
  return (
    <div className="run-progress">
      <ol>
        {run.steps.map((step) => (
          <li key={step.label} className={step.state}>
            <span className={`step-dot ${step.state}`} />
            {step.label}
          </li>
        ))}
      </ol>
      {run.status === 'error' && run.error && <p style={{ color: '#7a3030', marginTop: 6 }}>{run.error}</p>}
    </div>
  );
}

/** A short back-and-forth about ONE suggestion — questions or corrections,
 * grounded server-side in that suggestion's own evidence/steps. Replaces a
 * single "what should Mia change?" textarea with an actual conversation;
 * every message the person sends is still recorded as a correction
 * server-side (see backend/app/chat.py), so nothing about the existing
 * feedback/learning path changes underneath this. */
function ChatPanel({ suggestionId }: { suggestionId: string }) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const threadRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    let cancelled = false;
    backend
      .getChat(suggestionId)
      .then((list) => {
        if (!cancelled) {
          setMessages(list);
          setLoaded(true);
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setError(errMessage(err));
          setLoaded(true);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [suggestionId]);

  useEffect(() => {
    const el = threadRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages.length, sending]);

  const send = async () => {
    const text = input.trim();
    if (!text || sending) return;
    setInput('');
    setError(null);
    setMessages((prev) => [...prev, { role: 'user', content: text, createdAt: Date.now() }]);
    setSending(true);
    try {
      const res = await backend.sendChatMessage(suggestionId, text);
      setMessages(res.messages);
    } catch (err) {
      setError(errMessage(err));
    } finally {
      setSending(false);
    }
  };

  return (
    <div className="chat-panel">
      <div className="chat-thread" ref={threadRef}>
        {!loaded ? (
          <p className="chat-empty">Loading…</p>
        ) : messages.length === 0 ? (
          <p className="chat-empty">Ask Mia why she suggested this, or tell her what to change.</p>
        ) : (
          messages.map((m, i) => (
            <div key={i} className={`chat-bubble ${m.role}`}>
              {m.content}
            </div>
          ))
        )}
        {sending && <div className="chat-bubble mia chat-bubble--thinking">Mia is thinking…</div>}
      </div>
      {error && <p style={{ color: '#7a3030', fontSize: 12, marginBottom: 8 }}>{error}</p>}
      <form
        className="chat-input-row"
        onSubmit={(e) => {
          e.preventDefault();
          send();
        }}
      >
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Ask a question or describe a change…"
          maxLength={2000}
          disabled={sending}
        />
        <button type="submit" className="primary" disabled={sending || !input.trim()}>
          Send
        </button>
      </form>
    </div>
  );
}

interface SuggestionCardProps {
  suggestion: Suggestion;
  activeRun?: WorkflowRun;
  lastRun?: WorkflowRun;
  busy: boolean;
  variant: 'suggested' | 'active';
  highlighted?: boolean;
  googleConnected: boolean;
  onAccept: (s: Suggestion) => void;
  onRun: (s: Suggestion) => void;
  onForget: (s: Suggestion) => void;
  onSetRunMode: (s: Suggestion, mode: RunMode) => void;
}

function SuggestionCard({ suggestion, activeRun, lastRun, busy, variant, highlighted, googleConnected, onAccept, onRun, onForget, onSetRunMode }: SuggestionCardProps) {
  // Rules never carry a workflowKey server-side (see analyst.py), but this
  // guards any already-stored suggestion from an older run too.
  const runnable = Boolean(suggestion.workflowKey) && suggestion.kind !== 'rule';
  const running = activeRun?.status === 'running';
  const needsApproval = activeRun?.status === 'needs_approval';
  const [chatOpen, setChatOpen] = useState(false);
  const kindInfo = KIND_INFO[suggestion.kind];

  return (
    <article id={`suggestion-${suggestion.id}`} className={`card suggestion-card${highlighted ? ' card--highlight' : ''}`}>
      <div className="suggestion-card__top">
        <div>
          <span className="tag">{kindInfo.label}</span>{' '}
          {suggestion.kind !== 'rule' && (
            <span className={runnable ? 'tag' : 'tag tag--muted'}>{workflowLabel(suggestion.workflowKey)}</span>
          )}
        </div>
        <span className="meta-row">{relativeTime(suggestion.updatedAt)}</span>
      </div>
      <p className="kind-blurb">{kindInfo.blurb}</p>
      <h3>{suggestion.title}</h3>
      <p className="summary">{suggestion.summary}</p>
      <div className="detail-block">
        <div className="detail-label">Trigger</div>
        <p className="trigger-text">
          {suggestion.trigger || (suggestion.kind === 'rule' ? 'No trigger given yet.' : 'No trigger — runs on demand, only when you click Run.')}
        </p>
      </div>
      {suggestion.steps.length > 0 && (
        <div className="detail-block">
          <div className="detail-label">How this would work</div>
          <ol className="steps">
            {suggestion.steps.map((line, i) => (
              <li key={i}>{stripLeadingNumber(line)}</li>
            ))}
          </ol>
        </div>
      )}
      {suggestion.evidence.length > 0 && (
        <div className="detail-block">
          <div className="detail-label">Why Mia suggested this</div>
          <ul className="evidence">
            {suggestion.evidence.map((line, i) => (
              <li key={i}>{line}</li>
            ))}
          </ul>
        </div>
      )}
      <div className="meta-row">
        {confidencePct(suggestion.confidence)} confidence
        {suggestion.timeSavedPerWeekMinutes > 0 ? ` · about ${Math.round(suggestion.timeSavedPerWeekMinutes)} min/week saved` : ''}
      </div>
      {variant === 'active' && runnable && (
        <div className="run-mode-row">
          <span className="run-mode-label">When new input shows up:</span>
          <div className="run-mode-toggle" role="group" aria-label="Run mode">
            <button
              type="button"
              className={suggestion.runMode === 'auto' ? 'active' : ''}
              disabled={busy}
              onClick={() => onSetRunMode(suggestion, 'auto')}
            >
              Run automatically
            </button>
            <button
              type="button"
              className={suggestion.runMode === 'ask' ? 'active' : ''}
              disabled={busy}
              onClick={() => onSetRunMode(suggestion, 'ask')}
            >
              Ask me every time
            </button>
          </div>
        </div>
      )}
      {variant === 'active' && (
        <p className="auto-run-note">
          {suggestion.kind === 'rule'
            ? 'Mia applies this as a standing preference — nothing to run.'
            : !runnable
              ? 'Not yet automatable — nothing will run until this workflow is built.'
              : suggestion.runMode === 'auto'
                ? 'Mia runs this on her own, no click needed. You can also run it right now.'
                : "Mia will ask before running this. You can also run it right now."}
        </p>
      )}
      <div className="actions">
        {variant === 'suggested' && (
          <button className="primary" disabled={busy} onClick={() => onAccept(suggestion)}>
            Accept
          </button>
        )}
        {variant === 'active' && runnable && (
          <button
            className="primary"
            disabled={busy || running || needsApproval}
            title={!googleConnected ? 'Mia needs your Google account connected first' : undefined}
            onClick={() => onRun(suggestion)}
          >
            {running ? 'Running…' : needsApproval ? 'Waiting for approval…' : 'Run now'}
          </button>
        )}
        <button className="danger" disabled={busy} onClick={() => onForget(suggestion)}>
          {variant === 'active' ? 'Forget' : 'Dismiss'}
        </button>
        {variant === 'suggested' && (
          <button className="quiet" disabled={busy} onClick={() => setChatOpen((v) => !v)}>
            {chatOpen ? 'Close chat' : 'Edits or questions'}
          </button>
        )}
      </div>
      {chatOpen && <ChatPanel suggestionId={suggestion.id} />}
      {(activeRun || lastRun) && <RunProgress run={(activeRun ?? lastRun)!} />}
    </article>
  );
}

function IntegrationsPanel({
  auth,
  agentError,
}: {
  auth: GoogleAuthStatus | null;
  agentError: string | null;
}) {
  const status = !auth
    ? 'Checking…'
    : !auth.configured
      ? 'No Google OAuth client configured on the agent yet.'
      : auth.connected
        ? 'Connected — Mia can read Gmail and write to Sheets/Calendar.'
        : 'Not connected.';

  return (
    <section className="panel">
      <div className="panel__head">
        <h2>Integrations</h2>
      </div>
      <div className="card">
        <div className="integration-row">
          <div className="integration-row__meta">
            <span className={`dot ${auth?.connected ? 'dot--on' : 'dot--off'}`} />
            <div>
              <div style={{ fontWeight: 500 }}>Google account</div>
              <div style={{ fontSize: 12, color: 'var(--mia-ink-faint)' }}>{status}</div>
            </div>
          </div>
          {auth?.configured && !auth.connected && (
            <a className="btn primary" href={agent.authStartUrl()}>
              Connect Google
            </a>
          )}
          {auth?.connected && <span className="tag">Connected</span>}
        </div>
        {agentError && (
          <p style={{ color: '#7a3030', fontSize: 13, marginTop: 10 }}>
            Can’t reach the agent at {AGENT_URL}: {agentError}
          </p>
        )}
      </div>
    </section>
  );
}

function ApprovalBanner({ runs, onDecide }: { runs: WorkflowRun[]; onDecide: (run: WorkflowRun, decision: 'approve' | 'cancel') => void }) {
  const pending = runs.filter((r) => r.status === 'needs_approval');
  if (pending.length === 0) return null;
  return (
    <>
      {pending.map((run) => (
        <div className="banner banner--approval" key={run.runId}>
          <div>
            <strong>{run.approvalRequest?.title ?? 'Mia needs your approval'}</strong>
            <p style={{ margin: '4px 0 0' }}>{run.approvalRequest?.description}</p>
          </div>
          <div className="banner__actions">
            <button className="primary" onClick={() => onDecide(run, 'approve')}>
              Approve
            </button>
            <button className="danger" onClick={() => onDecide(run, 'cancel')}>
              Cancel
            </button>
          </div>
        </div>
      ))}
    </>
  );
}

function PendingTriggerBanner({
  triggers,
  onDecide,
}: {
  triggers: PendingTrigger[];
  onDecide: (trigger: PendingTrigger, decision: 'approve' | 'dismiss') => void;
}) {
  if (triggers.length === 0) return null;
  return (
    <>
      {triggers.map((trigger) => (
        <div className="banner banner--approval" key={trigger.id}>
          <div>
            <strong>{trigger.title}</strong>
            <p style={{ margin: '4px 0 0' }}>{trigger.description}</p>
          </div>
          <div className="banner__actions">
            <button className="primary" onClick={() => onDecide(trigger, 'approve')}>
              Run now
            </button>
            <button className="quiet" onClick={() => onDecide(trigger, 'dismiss')}>
              Not now
            </button>
          </div>
        </div>
      ))}
    </>
  );
}

function ConnectGooglePrompt({
  title,
  configured,
  onDismiss,
}: {
  title: string;
  configured: boolean;
  onDismiss: () => void;
}) {
  return (
    <div className="banner banner--approval">
      <div>
        <strong>Connect Google before running this</strong>
        <p style={{ margin: '4px 0 0' }}>
          {configured
            ? `"${title}" reads from Gmail and writes to Sheets/Calendar — connect your Google account below first.`
            : `"${title}" can't run yet: the agent has no Google OAuth client configured. Someone needs to set that up before this is runnable.`}
        </p>
      </div>
      <div className="banner__actions">
        {configured && (
          <a className="btn primary" href={agent.authStartUrl()}>
            Connect Google
          </a>
        )}
        <button className="quiet" onClick={onDismiss}>
          Dismiss
        </button>
      </div>
    </div>
  );
}

function HistoryPanel({ runs }: { runs: WorkflowRun[] }) {
  const finished = runs.filter((r) => r.status === 'done' || r.status === 'error');
  return (
    <section className="panel">
      <div className="panel__head">
        <h2>Recent history</h2>
        <span className="eyebrow">Last {finished.length} run{finished.length === 1 ? '' : 's'}</span>
      </div>
      {finished.length === 0 ? (
        <p className="panel__empty">Nothing has run yet. Runs you start from a suggestion will show up here.</p>
      ) : (
        <div className="card">
          {finished.map((run) => (
            <div className="history-row" key={run.runId}>
              <div className="history-row__left">
                <span className="history-row__title">
                  {workflowLabel(run.workflowKey)}
                  <span className={`trigger-chip trigger-chip--${run.triggeredBy}`}>
                    {run.triggeredBy === 'auto' ? 'Auto' : 'Manual'}
                  </span>
                </span>
                <span className="history-row__meta">
                  {relativeTime(run.startedAt)}
                  {run.status === 'error' && run.error ? ` · ${run.error}` : ''}
                  {run.status === 'done' && run.result && typeof run.result.sheetUrl === 'string' ? ' · row appended' : ''}
                  {run.status === 'done' && run.result && typeof run.result.htmlLink === 'string' ? ' · event created' : ''}
                </span>
              </div>
              <span className={`status-chip status-chip--${run.status}`}>{run.status === 'done' ? 'Succeeded' : 'Failed'}</span>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

export function App() {
  const [suggestions, setSuggestions] = useState<Suggestion[]>([]);
  const [runs, setRuns] = useState<WorkflowRun[]>([]);
  const [auth, setAuth] = useState<GoogleAuthStatus | null>(null);
  const [backendError, setBackendError] = useState<string | null>(null);
  const [agentError, setAgentError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [busyIds, setBusyIds] = useState<Set<string>>(new Set());
  const [highlightId, setHighlightId] = useState<string | null>(null);
  const [connectPrompt, setConnectPrompt] = useState<string | null>(null);
  const [suggestedShown, setSuggestedShown] = useState(6);
  const [pending, setPending] = useState<PendingTrigger[]>([]);

  const refreshSuggestions = useCallback(async () => {
    try {
      const list = await backend.listSuggestions();
      setSuggestions(list);
      setBackendError(null);
    } catch (err) {
      setBackendError(errMessage(err));
    }
  }, []);

  const refreshRuns = useCallback(async () => {
    try {
      const list = await agent.listRuns();
      setRuns(list);
      setAgentError(null);
    } catch (err) {
      setAgentError(errMessage(err));
    }
  }, []);

  const refreshAuth = useCallback(async () => {
    try {
      const status = await agent.authStatus();
      setAuth(status);
      setAgentError(null);
    } catch (err) {
      setAgentError(errMessage(err));
    }
  }, []);

  const refreshPending = useCallback(async () => {
    try {
      const list = await agent.listPending();
      setPending(list);
      setAgentError(null);
    } catch (err) {
      setAgentError(errMessage(err));
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    async function tick() {
      await Promise.all([refreshSuggestions(), refreshRuns(), refreshAuth(), refreshPending()]);
      if (!cancelled) setLoaded(true);
    }
    tick();
    const interval = setInterval(tick, POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [refreshSuggestions, refreshRuns, refreshAuth, refreshPending]);

  // Two ways this page is opened with a query string: Google redirecting back
  // after the OAuth callback (?connected=1|0), and the side panel's "See
  // details" link on a suggestion (?suggestion=<id>) scrolling it into view.
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.has('connected')) refreshAuth();
    const suggestionId = params.get('suggestion');
    if (suggestionId) setHighlightId(suggestionId);
    if (params.toString()) window.history.replaceState({}, '', window.location.pathname);
  }, [refreshAuth]);

  useEffect(() => {
    if (!loaded || !highlightId) return;
    const el = document.getElementById(`suggestion-${highlightId}`);
    el?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    const timer = setTimeout(() => setHighlightId(null), 4000);
    return () => clearTimeout(timer);
  }, [loaded, highlightId]);

  // Once Google actually connects, the prompt that sent them there is moot.
  useEffect(() => {
    if (auth?.connected) setConnectPrompt(null);
  }, [auth?.connected]);

  const setBusy = (id: string, busy: boolean) => {
    setBusyIds((prev) => {
      const next = new Set(prev);
      if (busy) next.add(id);
      else next.delete(id);
      return next;
    });
  };

  const handleRun = useCallback(
    async (suggestion: Suggestion) => {
      const workflowKey = suggestion.workflowKey;
      if (!workflowKey) return;
      // Never let a run attempt reach the agent without Google connected —
      // that would just be a guaranteed "missing client secret"/401 error.
      // Tell them what to do instead of letting them find out the hard way.
      if (!auth?.connected) {
        setConnectPrompt(suggestion.title);
        return;
      }
      setBusy(suggestion.id, true);
      try {
        if (suggestion.status === 'proposed') {
          await backend.feedback(suggestion.id, 'accept');
        }
        await agent.runWorkflow(workflowKey, suggestion.id);
        await Promise.all([refreshSuggestions(), refreshRuns()]);
      } catch (err) {
        setAgentError(errMessage(err));
      } finally {
        setBusy(suggestion.id, false);
      }
    },
    [refreshSuggestions, refreshRuns, auth],
  );

  const handleAccept = useCallback(
    async (suggestion: Suggestion) => {
      setBusy(suggestion.id, true);
      try {
        await backend.feedback(suggestion.id, 'accept');
        await refreshSuggestions();
      } catch (err) {
        setBackendError(errMessage(err));
      } finally {
        setBusy(suggestion.id, false);
      }
    },
    [refreshSuggestions],
  );

  const handleForget = useCallback(
    async (suggestion: Suggestion) => {
      setBusy(suggestion.id, true);
      try {
        await backend.feedback(suggestion.id, 'dismiss');
        await refreshSuggestions();
      } catch (err) {
        setBackendError(errMessage(err));
      } finally {
        setBusy(suggestion.id, false);
      }
    },
    [refreshSuggestions],
  );

  const handleSetRunMode = useCallback(
    async (suggestion: Suggestion, mode: RunMode) => {
      if (suggestion.runMode === mode) return;
      setBusy(suggestion.id, true);
      try {
        await backend.setRunMode(suggestion.id, mode);
        await refreshSuggestions();
      } catch (err) {
        setBackendError(errMessage(err));
      } finally {
        setBusy(suggestion.id, false);
      }
    },
    [refreshSuggestions],
  );

  const handlePendingDecision = useCallback(
    async (trigger: PendingTrigger, decision: 'approve' | 'dismiss') => {
      try {
        if (decision === 'approve') await agent.approvePending(trigger.id);
        else await agent.dismissPending(trigger.id);
        await Promise.all([refreshPending(), refreshRuns()]);
      } catch (err) {
        setAgentError(errMessage(err));
      }
    },
    [refreshPending, refreshRuns],
  );

  const handleApprovalDecision = useCallback(
    async (run: WorkflowRun, decision: 'approve' | 'cancel') => {
      try {
        await agent.approveRun(run.runId, decision);
        await refreshRuns();
      } catch (err) {
        setAgentError(errMessage(err));
      }
    },
    [refreshRuns],
  );

  const runsBySuggestion = useMemo(() => {
    const map = new Map<string, WorkflowRun[]>();
    for (const run of runs) {
      if (!run.suggestionId) continue;
      const existing = map.get(run.suggestionId) ?? [];
      existing.push(run);
      map.set(run.suggestionId, existing);
    }
    return map;
  }, [runs]);

  const active = suggestions.filter((s) => s.status === 'accepted' || s.status === 'built');
  const suggested = suggestions.filter((s) => s.status === 'proposed');
  // A deep-linked suggestion (from the side panel's "See details" link) must
  // stay visible even if it's further down the list than the current page.
  const highlightIndex = highlightId ? suggested.findIndex((s) => s.id === highlightId) : -1;
  const suggestedVisibleCount = highlightIndex >= 0 ? Math.max(suggestedShown, highlightIndex + 1) : suggestedShown;
  const visibleSuggested = suggested.slice(0, suggestedVisibleCount);
  const suggestedRemaining = suggested.length - visibleSuggested.length;
  const miaState = overallMiaState(suggestions, runs);

  return (
    <div className="dashboard">
      <div className="dashboard__inner">
        <header className="dashboard__header">
          <MiaAvatar state={miaState} size={56} />
          <div>
            <h1>Mia</h1>
            <p>Connect Google, review what Mia noticed, and decide what runs.</p>
          </div>
        </header>

        <ApprovalBanner runs={runs} onDecide={handleApprovalDecision} />
        <PendingTriggerBanner triggers={pending} onDecide={handlePendingDecision} />
        {connectPrompt && (
          <ConnectGooglePrompt
            title={connectPrompt}
            configured={Boolean(auth?.configured)}
            onDismiss={() => setConnectPrompt(null)}
          />
        )}
        {backendError && (
          <div className="banner banner--error">
            Can’t reach the detection backend at {BACKEND_URL}: {backendError}
          </div>
        )}

        <IntegrationsPanel auth={auth} agentError={agentError} />

        <section className="panel">
          <div className="panel__head">
            <h2>Active automations</h2>
            <span className="eyebrow">{active.length} enabled</span>
          </div>
          {!loaded ? (
            <p className="panel__empty">Loading…</p>
          ) : active.length === 0 ? (
            <p className="panel__empty">
              Nothing enabled yet. Accept a suggestion below — Mia will run it on her own from then on, no further clicks
              needed, and still pause for your approval on anything consequential.
            </p>
          ) : (
            <div className="stack">
              {active.map((s) => {
                const forSuggestion = runsBySuggestion.get(s.id) ?? [];
                const activeRun = forSuggestion.find((r) => r.status === 'running' || r.status === 'needs_approval');
                const lastRun = forSuggestion[0];
                return (
                  <SuggestionCard
                    key={s.id}
                    suggestion={s}
                    activeRun={activeRun}
                    lastRun={lastRun}
                    busy={busyIds.has(s.id)}
                    variant="active"
                    highlighted={s.id === highlightId}
                    googleConnected={Boolean(auth?.connected)}
                    onAccept={handleAccept}
                    onRun={handleRun}
                    onForget={handleForget}
                    onSetRunMode={handleSetRunMode}
                  />
                );
              })}
            </div>
          )}
        </section>

        <section className="panel">
          <div className="panel__head">
            <h2>Suggested by Mia</h2>
            <span className="eyebrow">{suggested.length} new</span>
          </div>
          {!loaded ? (
            <p className="panel__empty">Loading…</p>
          ) : suggested.length === 0 ? (
            <p className="panel__empty">Nothing new. Mia is still looking for repeated patterns.</p>
          ) : (
            <>
              <div className="stack">
                {visibleSuggested.map((s) => {
                  const forSuggestion = runsBySuggestion.get(s.id) ?? [];
                  const activeRun = forSuggestion.find((r) => r.status === 'running' || r.status === 'needs_approval');
                  const lastRun = forSuggestion[0];
                  return (
                    <SuggestionCard
                      key={s.id}
                      suggestion={s}
                      activeRun={activeRun}
                      lastRun={lastRun}
                      busy={busyIds.has(s.id)}
                      variant="suggested"
                      highlighted={s.id === highlightId}
                      googleConnected={Boolean(auth?.connected)}
                      onAccept={handleAccept}
                      onRun={handleRun}
                      onForget={handleForget}
                      onSetRunMode={handleSetRunMode}
                    />
                  );
                })}
              </div>
              {suggestedRemaining > 0 && (
                <button className="quiet show-more" onClick={() => setSuggestedShown((n) => n + 10)}>
                  Show {Math.min(suggestedRemaining, 10)} more ({suggestedRemaining} left)
                </button>
              )}
            </>
          )}
        </section>

        <HistoryPanel runs={runs} />
      </div>
    </div>
  );
}
