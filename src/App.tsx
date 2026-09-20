/**
 * MIA dashboard — the "workflows app" the extension's side panel points to.
 * Accepting/dismissing a proposal already happens in the side panel; running
 * a workflow (the one action Mia never takes on her own) happens here.
 *
 * Talks to two independent local processes:
 *   - Kathy's detection backend (suggestions)   see src/lib/api.ts BACKEND_URL
 *   - Poshitha's agent (execution + OAuth)      see src/lib/api.ts AGENT_URL
 */
import { useCallback, useEffect, useMemo, useRef, useState, type MouseEvent, type ReactNode } from 'react';
import type { MiaState } from './components/mia/mia-personality';
import miaIcon from './assets/mia-icon.png';
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
// MiaAvatar used to be what pulled the shared tokens in; the dashboard no
// longer renders it, so import them here explicitly.
import './components/mia/mia-theme.css';
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

/**
 * Every card here opens by clicking its summary area. Real controls inside
 * that area — Accept, Dismiss, Connect Google, the chat input — must fire
 * their own handler and nothing else, so a click that lands on one is ignored
 * by the toggle rather than each control having to stop propagation.
 */
const INTERACTIVE = 'button, a, input, textarea, select, label, form';

function toggleOnBackgroundClick(toggle: () => void) {
  return (event: MouseEvent) => {
    if ((event.target as HTMLElement).closest(INTERACTIVE)) return;
    toggle();
  };
}

/** Two diagonal arrows: this opens something larger, it does not unfold. */
function ExpandIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round">
      <path d="M14 4h6v6M20 4l-7.5 7.5M10 20H4v-6M4 20l7.5-7.5" />
    </svg>
  );
}

/**
 * A centred popup built on <dialog>, so focus trapping, inertness of the page
 * behind it, and Esc all come from the platform rather than being re-invented.
 */
function Modal({ title, onClose, children, wide }: { title: string; onClose: () => void; children: ReactNode; wide?: boolean }) {
  const ref = useRef<HTMLDialogElement | null>(null);

  useEffect(() => {
    const el = ref.current;
    if (el && !el.open) el.showModal();
    return () => {
      if (el?.open) el.close();
    };
  }, []);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    // Esc fires `cancel`; take it over so closing always goes through React.
    const cancel = (event: Event) => {
      event.preventDefault();
      onClose();
    };
    el.addEventListener('cancel', cancel);
    return () => el.removeEventListener('cancel', cancel);
  }, [onClose]);

  return (
    <dialog
      ref={ref}
      className={`modal${wide ? ' modal--wide' : ''}`}
      aria-label={title}
      // Only a click on the backdrop itself lands on the dialog element.
      onClick={(event) => {
        if (event.target === ref.current) onClose();
      }}
    >
      <div className="modal__card">
        <div className="modal__head">
          <h2>{title}</h2>
          <button type="button" className="modal__close" onClick={onClose} aria-label="Close">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
              <path d="M6 6l12 12M18 6L6 18" />
            </svg>
          </button>
        </div>
        <div className="modal__body">{children}</div>
      </div>
    </dialog>
  );
}

interface SummaryCardProps {
  /** Anchor the rail points at. */
  id?: string;
  title: string;
  meta?: ReactNode;
  /** The whole of what this card shows in the grid — never the detail. */
  summary?: ReactNode;
  /** Controls that live outside the open target so clicking them never opens. */
  actions?: ReactNode;
  onOpen: () => void;
  className?: string;
}

/**
 * A fixed-height tile in the grid. It never grows: everything beyond the
 * summary lives in the popup, which is what keeps the page on one screen no
 * matter how much data arrives.
 */
function SummaryCard({ id, title, meta, summary, actions, onOpen, className }: SummaryCardProps) {
  return (
    <section id={id} className={`card panel-card${className ? ` ${className}` : ''}`}>
      <div className="panel-card__head" onClick={toggleOnBackgroundClick(onOpen)}>
        <h2 className="panel-card__heading">
          <button type="button" className="panel-card__toggle" onClick={onOpen}>
            <span>{title}</span>
            <span className="panel-card__expand" aria-hidden="true">
              <ExpandIcon />
            </span>
            <span className="sr-only">— open</span>
          </button>
        </h2>
        <div className="panel-card__head-end">
          {meta !== undefined && <span className="eyebrow">{meta}</span>}
          {actions}
        </div>
      </div>
      {summary !== undefined && (
        <div className="panel-card__summary" onClick={toggleOnBackgroundClick(onOpen)}>
          {summary}
        </div>
      )}
    </section>
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
  /** True inside the popup: trigger, steps, evidence and the chat all render. */
  detail?: boolean;
  /** Grid cards hand the page a request to open the popup instead of growing. */
  onOpenDetail?: (suggestion: Suggestion, opts?: { chat?: boolean }) => void;
  chatInitiallyOpen?: boolean;
  onAccept: (s: Suggestion) => void;
  onRun: (s: Suggestion) => void;
  onForget: (s: Suggestion) => void;
  onSetRunMode: (s: Suggestion, mode: RunMode) => void;
}

function SuggestionCard({
  suggestion,
  activeRun,
  lastRun,
  busy,
  variant,
  highlighted,
  googleConnected,
  detail = false,
  onOpenDetail,
  chatInitiallyOpen = false,
  onAccept,
  onRun,
  onForget,
  onSetRunMode,
}: SuggestionCardProps) {
  // Rules never carry a workflowKey server-side (see analyst.py), but this
  // guards any already-stored suggestion from an older run too.
  const runnable = Boolean(suggestion.workflowKey) && suggestion.kind !== 'rule';
  const running = activeRun?.status === 'running';
  const needsApproval = activeRun?.status === 'needs_approval';
  const [chatOpen, setChatOpen] = useState(chatInitiallyOpen);
  const kindInfo = KIND_INFO[suggestion.kind];

  return (
    <article
      id={detail ? undefined : `suggestion-${suggestion.id}`}
      className={`card suggestion-card${highlighted ? ' card--highlight' : ''}${detail ? ' suggestion-card--detail' : ''}`}
    >
      <div
        className="suggestion-card__summary"
        onClick={detail ? undefined : toggleOnBackgroundClick(() => onOpenDetail?.(suggestion))}
      >
        <div className="suggestion-card__top">
          <div>
            <span className="tag">{kindInfo.label}</span>{' '}
            {suggestion.kind !== 'rule' && (
              <span className={runnable ? 'tag' : 'tag tag--muted'}>{workflowLabel(suggestion.workflowKey)}</span>
            )}
          </div>
          <div className="suggestion-card__top-end">
            <span className="meta-row">{relativeTime(suggestion.updatedAt)}</span>
            {!detail && (
              <button type="button" className="card-expand" onClick={() => onOpenDetail?.(suggestion)}>
                <ExpandIcon />
                <span className="sr-only">Show details</span>
              </button>
            )}
          </div>
        </div>
        <p className="kind-blurb">{kindInfo.blurb}</p>
        <h3>{suggestion.title}</h3>
        <p className="summary">{suggestion.summary}</p>
      </div>
      {detail && (
        <div className="suggestion-card__detail">
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
          <button
            className="quiet"
            disabled={busy}
            // In the grid the chat has nowhere to go, so asking for it opens
            // the popup with the thread already showing.
            onClick={() => (detail ? setChatOpen((v) => !v) : onOpenDetail?.(suggestion, { chat: true }))}
          >
            {detail && chatOpen ? 'Close chat' : 'Edits or questions'}
          </button>
        )}
      </div>
      {detail && chatOpen && <ChatPanel suggestionId={suggestion.id} />}
      {(activeRun || lastRun) && <RunProgress run={(activeRun ?? lastRun)!} />}
    </article>
  );
}

function integrationStatus(auth: GoogleAuthStatus | null): string {
  return !auth
    ? 'Checking…'
    : !auth.configured
      ? 'No Google OAuth client configured on the agent yet.'
      : auth.connected
        ? 'Connected — Mia can read Gmail and write to Sheets/Calendar.'
        : 'Not connected.';
}

function IntegrationsSummary({ auth, agentError }: { auth: GoogleAuthStatus | null; agentError: string | null }) {
  const reachError = agentError ? `Can’t reach the agent at ${AGENT_URL}` : null;
  return (
    <div className="integration-row__meta">
      <span className={`dot ${auth?.connected ? 'dot--on' : 'dot--off'}`} />
      <div className="integration-row__text">
        <div className="integration-row__name">Google account</div>
        <div className={`integration-status${reachError ? ' integration-status--error' : ''}`}>
          {reachError ?? integrationStatus(auth)}
        </div>
      </div>
    </div>
  );
}

function IntegrationsDetail({ auth, agentError }: { auth: GoogleAuthStatus | null; agentError: string | null }) {
  return (
    <>
      <div className="integration-row">
        <div className="integration-row__meta">
          <span className={`dot ${auth?.connected ? 'dot--on' : 'dot--off'}`} />
          <div className="integration-row__text">
            <div className="integration-row__name">Google account</div>
            <div className="integration-status">{integrationStatus(auth)}</div>
          </div>
        </div>
        {auth?.configured && !auth.connected && (
          <a className="btn primary" href={agent.authStartUrl()}>
            Connect Google
          </a>
        )}
        {auth?.connected && <span className="tag">Connected</span>}
      </div>
      {agentError ? (
        <p className="integration-error">
          Can’t reach the agent at {AGENT_URL}: {agentError}
        </p>
      ) : (
        <p className="integration-detail integration-detail--muted">Agent reachable at {AGENT_URL}.</p>
      )}
    </>
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

function HistoryRow({ run }: { run: WorkflowRun }) {
  return (
    <div className="history-row">
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
  );
}

function finishedRunsOf(runs: WorkflowRun[]): WorkflowRun[] {
  return runs.filter((r) => r.status === 'done' || r.status === 'error');
}

function HistorySummary({ runs }: { runs: WorkflowRun[] }) {
  const finished = finishedRunsOf(runs);
  if (finished.length === 0) {
    return <p className="panel__empty">Nothing has run yet. Runs you start from a suggestion will show up here.</p>;
  }
  return <HistoryRow run={finished[0]} />;
}

function HistoryDetail({ runs }: { runs: WorkflowRun[] }) {
  const finished = finishedRunsOf(runs);
  if (finished.length === 0) {
    return <p className="panel__empty">Nothing has run yet. Runs you start from a suggestion will show up here.</p>;
  }
  return (
    <>
      {finished.map((run) => (
        <HistoryRow key={run.runId} run={run} />
      ))}
    </>
  );
}

/** Plain strokes, sized by the rail. No icon dependency for six glyphs. */
function NavIcon({ name }: { name: string }) {
  const common = { width: 19, height: 19, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', strokeWidth: 1.7, strokeLinecap: 'round' as const, strokeLinejoin: 'round' as const };
  if (name === 'overview')
    return (
      <svg {...common}>
        <rect x="3" y="3" width="7" height="7" rx="2" />
        <rect x="14" y="3" width="7" height="7" rx="2" />
        <rect x="3" y="14" width="7" height="7" rx="2" />
        <rect x="14" y="14" width="7" height="7" rx="2" />
      </svg>
    );
  if (name === 'suggested')
    return (
      <svg {...common}>
        <path d="M12 3l2.1 4.9L19 10l-4.9 2.1L12 17l-2.1-4.9L5 10l4.9-2.1z" />
        <path d="M18 17l.8 1.9 1.9.8-1.9.8-.8 1.9-.8-1.9-1.9-.8 1.9-.8z" />
      </svg>
    );
  if (name === 'automations')
    return (
      <svg {...common}>
        <path d="M13 2L4.5 13.5H11l-.8 8.5L19 10.5h-6.5z" />
      </svg>
    );
  if (name === 'history')
    return (
      <svg {...common}>
        <circle cx="12" cy="12" r="9" />
        <path d="M12 7v5l3.2 1.9" />
      </svg>
    );
  if (name === 'integrations')
    return (
      <svg {...common}>
        <path d="M9 2v6M15 2v6" />
        <path d="M6 8h12v4a6 6 0 0 1-12 0z" />
        <path d="M12 18v4" />
      </svg>
    );
  return (
    <svg {...common}>
      <circle cx="12" cy="12" r="3.2" />
      <path d="M19.4 14.5a1.7 1.7 0 0 0 .3 1.9l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-2.9 1.2v.2a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.6 1.7 1.7 0 0 0-1.9.4l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0-1.2-2.9h-.2a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.6-1.1 1.7 1.7 0 0 0-.4-1.9l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.9.3h.1A1.7 1.7 0 0 0 10 3.5v-.2a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 2.9 1.2l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.9v.1a1.7 1.7 0 0 0 1.6 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z" />
    </svg>
  );
}

const NAV = [
  { id: 'overview', label: 'Overview' },
  { id: 'suggested', label: 'Suggested by Mia' },
  { id: 'automations', label: 'Active automations' },
  { id: 'history', label: 'Recent history' },
  { id: 'integrations', label: 'Integrations' },
];

function Rail({ current, onNavigate }: { current: string; onNavigate: (id: string) => void }) {
  return (
    <nav className="rail" aria-label="Sections">
      <img className="rail__logo" src={miaIcon} alt="Mia" width={36} height={36} />
      <div className="rail__group">
        {NAV.map((item) => (
          <button
            key={item.id}
            type="button"
            className={`rail__btn${current === item.id ? ' rail__btn--on' : ''}`}
            aria-current={current === item.id ? 'true' : undefined}
            title={item.label}
            onClick={() => onNavigate(item.id)}
          >
            <NavIcon name={item.id} />
            <span className="sr-only">{item.label}</span>
          </button>
        ))}
      </div>
      <button
        type="button"
        className={`rail__btn rail__btn--foot${current === 'settings' ? ' rail__btn--on' : ''}`}
        aria-current={current === 'settings' ? 'true' : undefined}
        title="Settings"
        onClick={() => onNavigate('settings')}
      >
        <NavIcon name="settings" />
        <span className="sr-only">Settings</span>
      </button>
    </nav>
  );
}

function StatTile({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <div className="stat">
      <span className="stat__label">{label}</span>
      <span className="stat__value">{value}</span>
      {note && <span className="stat__note">{note}</span>}
    </div>
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
  // Each card opens independently; this is not an exclusive accordion.
  // One centred popup at a time — a modal is exclusive by nature, unlike the
  // inline accordions it replaces.
  const [modal, setModal] = useState<{ kind: string; id?: string; chat?: boolean } | null>(null);
  const [section, setSection] = useState('overview');
  // Polling is the only thing on this page that keeps running on its own, so
  // it is the one thing Settings can meaningfully turn off.
  const [livePolling, setLivePolling] = useState(true);

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

  const refreshAll = useCallback(async () => {
    await Promise.all([refreshSuggestions(), refreshRuns(), refreshAuth(), refreshPending()]);
    setLoaded(true);
  }, [refreshSuggestions, refreshRuns, refreshAuth, refreshPending]);

  useEffect(() => {
    refreshAll();
    // Paused still loads once; it only stops the repeat.
    if (!livePolling) return;
    const interval = setInterval(refreshAll, POLL_MS);
    return () => clearInterval(interval);
  }, [refreshAll, livePolling]);

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

  // The side panel's "See details" link promised detail, so open it directly.
  useEffect(() => {
    if (!loaded || !highlightId) return;
    setModal({ kind: 'suggestion', id: highlightId });
    const timer = setTimeout(() => setHighlightId(null), 4000);
    return () => clearTimeout(timer);
  }, [loaded, highlightId]);

  // Once Google actually connects, the prompt that sent them there is moot.
  useEffect(() => {
    if (auth?.connected) setConnectPrompt(null);
  }, [auth?.connected]);

  // Every rail icon but Overview opens that card as a centred popup.
  const navigate = useCallback((id: string) => {
    setSection(id);
    setModal(id === 'overview' ? null : { kind: id });
  }, []);

  const openSuggestion = useCallback((suggestion: Suggestion, opts?: { chat?: boolean }) => {
    setModal({ kind: 'suggestion', id: suggestion.id, chat: opts?.chat });
  }, []);

  const closeModal = useCallback(() => setModal(null), []);

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
  const modalSuggestion = modal?.kind === 'suggestion' ? suggestions.find((s) => s.id === modal.id) : undefined;

  const cardFor = (s: Suggestion, variant: 'suggested' | 'active', detail: boolean, chat = false) => {
    const forSuggestion = runsBySuggestion.get(s.id) ?? [];
    return (
      <SuggestionCard
        key={s.id}
        suggestion={s}
        activeRun={forSuggestion.find((r) => r.status === 'running' || r.status === 'needs_approval')}
        lastRun={forSuggestion[0]}
        busy={busyIds.has(s.id)}
        variant={variant}
        highlighted={s.id === highlightId}
        googleConnected={Boolean(auth?.connected)}
        detail={detail}
        chatInitiallyOpen={chat}
        onOpenDetail={openSuggestion}
        onAccept={handleAccept}
        onRun={handleRun}
        onForget={handleForget}
        onSetRunMode={handleSetRunMode}
      />
    );
  };
  const finishedRuns = runs.filter((r) => r.status === 'done' || r.status === 'error');
  const succeededRuns = finishedRuns.filter((r) => r.status === 'done').length;
  const minutesSaved = active.reduce((total, s) => total + (s.timeSavedPerWeekMinutes || 0), 0);
  const STATE_LABEL: Record<MiaState, string> = {
    idle: 'Watching for patterns',
    thinking: 'Looking at what you did',
    suggesting: 'Has something for you',
    confirming: 'Waiting on your approval',
    running: 'Running a workflow',
    success: 'Finished a run',
    failure: 'A run did not finish',
  };

  return (
    <div className="dashboard">
      {/* Same drifting lilac field as the side panel. Only transform animates,
          so each blurred blob rasterises once and this costs no repaints. */}
      <div className="aurora" aria-hidden="true">
        <span />
        <span />
        <span />
        <span />
      </div>

      <Rail current={section} onNavigate={navigate} />

      <div className="dashboard__inner">
        <header className="dashboard__header" id="card-overview">
          <img className="dashboard__mark" src={miaIcon} alt="" width={52} height={52} />
          <div className="dashboard__title">
            <h1>Mia</h1>
            <p>Here's what Mia can help with.</p>
          </div>
          <span className={`state-pill state-pill--${miaState}`}>
            <span className="state-pill__dot" />
            {STATE_LABEL[miaState]}
          </span>
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

        <div className="stats">
          <StatTile label="New suggestions" value={String(suggested.length)} note="waiting on you" />
          <StatTile
            label="Automations on"
            value={String(active.length)}
            note={active.length === 0 ? 'none enabled yet' : 'running for you'}
          />
          <StatTile
            label="Runs"
            value={String(finishedRuns.length)}
            note={finishedRuns.length === 0 ? 'nothing yet' : `${succeededRuns} succeeded`}
          />
          <StatTile
            label="Saved / week"
            value={minutesSaved > 0 ? `${Math.round(minutesSaved)} min` : '—'}
            note={minutesSaved > 0 ? 'across your automations' : 'accept one to start'}
          />
        </div>

        <div className="dashboard__grid">
          {/* The one card that lists rather than summarises. Its body scrolls
              inside itself so the page stays one screen at any list length. */}
          <section id="card-suggested" className="card panel-card panel-card--suggested">
            <div className="panel-card__head">
              <h2 className="panel-card__heading">
                <button type="button" className="panel-card__toggle" onClick={() => navigate('suggested')}>
                  <span>Suggested by Mia</span>
                  <span className="panel-card__expand" aria-hidden="true">
                    <ExpandIcon />
                  </span>
                  <span className="sr-only">— open</span>
                </button>
              </h2>
              <div className="panel-card__head-end">
                <span className="eyebrow">{suggested.length} new</span>
              </div>
            </div>
            <div className="panel-card__body panel-card__body--scroll">
              {!loaded ? (
                <p className="panel__empty">Loading…</p>
              ) : suggested.length === 0 ? (
                <p className="panel__empty">Nothing new. Mia is still looking for repeated patterns.</p>
              ) : (
                <>
                  <div className="stack">{visibleSuggested.map((s) => cardFor(s, 'suggested', false))}</div>
                  {suggestedRemaining > 0 && (
                    <button className="quiet show-more" onClick={() => setSuggestedShown((n) => n + 10)}>
                      Show {Math.min(suggestedRemaining, 10)} more ({suggestedRemaining} left)
                    </button>
                  )}
                </>
              )}
            </div>
          </section>

          <SummaryCard
            id="card-integrations"
            className="panel-card--integrations"
            title="Integrations"
            actions={
              <>
                {auth?.configured && !auth.connected && (
                  <a className="btn primary" href={agent.authStartUrl()}>
                    Connect Google
                  </a>
                )}
                {auth?.connected && <span className="tag">Connected</span>}
              </>
            }
            summary={<IntegrationsSummary auth={auth} agentError={agentError} />}
            onOpen={() => navigate('integrations')}
          />

          <SummaryCard
            id="card-automations"
            className="panel-card--automations"
            title="Active automations"
            meta={`${active.length} enabled`}
            summary={
              !loaded ? (
                <p className="panel__empty">Loading…</p>
              ) : active.length === 0 ? (
                <p className="panel__empty">
                  Nothing enabled yet. Accept a suggestion — Mia will run it on her own from then on, and still pause for
                  your approval on anything consequential.
                </p>
              ) : (
                <p className="panel__empty panel__empty--plain">
                  {active.length === 1 ? '1 automation is' : `${active.length} automations are`} enabled. Open to run,
                  change when they run, or forget them.
                </p>
              )
            }
            onOpen={() => navigate('automations')}
          />

          <SummaryCard
            id="card-history"
            className="panel-card--history"
            title="Recent history"
            meta={`Last ${finishedRuns.length} run${finishedRuns.length === 1 ? '' : 's'}`}
            summary={<HistorySummary runs={runs} />}
            onOpen={() => navigate('history')}
          />

          <SummaryCard
            id="card-settings"
            className="panel-card--settings"
            title="Settings"
            meta={livePolling ? 'Live' : 'Paused'}
            summary={
              <p className="panel__empty panel__empty--plain">
                {livePolling ? `Refreshing every ${POLL_MS / 1000}s.` : 'Live updates paused.'} Google{' '}
                {auth?.connected ? 'connected' : 'not connected'}.
              </p>
            }
            onOpen={() => navigate('settings')}
          />
        </div>
      </div>

      {modal?.kind === 'suggested' && (
        <Modal title="Suggested by Mia" onClose={closeModal} wide>
          {suggested.length === 0 ? (
            <p className="panel__empty">Nothing new. Mia is still looking for repeated patterns.</p>
          ) : (
            <div className="stack">{suggested.map((s) => cardFor(s, 'suggested', true))}</div>
          )}
        </Modal>
      )}

      {modal?.kind === 'suggestion' && modalSuggestion && (
        <Modal title={modalSuggestion.title} onClose={closeModal} wide>
          {cardFor(modalSuggestion, modalSuggestion.status === 'proposed' ? 'suggested' : 'active', true, Boolean(modal.chat))}
        </Modal>
      )}

      {modal?.kind === 'automations' && (
        <Modal title="Active automations" onClose={closeModal} wide>
          {active.length === 0 ? (
            <p className="panel__empty">
              Nothing enabled yet. Accept a suggestion — Mia will run it on her own from then on, no further clicks
              needed, and still pause for your approval on anything consequential.
            </p>
          ) : (
            <div className="stack">{active.map((s) => cardFor(s, 'active', true))}</div>
          )}
        </Modal>
      )}

      {modal?.kind === 'integrations' && (
        <Modal title="Integrations" onClose={closeModal}>
          <IntegrationsDetail auth={auth} agentError={agentError} />
        </Modal>
      )}

      {modal?.kind === 'history' && (
        <Modal title="Recent history" onClose={closeModal}>
          <HistoryDetail runs={runs} />
        </Modal>
      )}

      {modal?.kind === 'settings' && (
        <Modal title="Settings" onClose={closeModal}>
          <div className="setting-row">
            <div>
              <div className="setting-row__name">Live updates</div>
              <p className="setting-row__note">
                {livePolling
                  ? `Mia re-checks both services every ${POLL_MS / 1000}s.`
                  : 'Paused — nothing refreshes until you resume or refresh by hand.'}
              </p>
            </div>
            <div className="setting-row__actions">
              <button onClick={() => setLivePolling((v) => !v)}>{livePolling ? 'Pause' : 'Resume'}</button>
              <button className="quiet" onClick={() => refreshAll()}>
                Refresh now
              </button>
            </div>
          </div>
          <div className="setting-row">
            <div>
              <div className="setting-row__name">Google account</div>
              <p className="setting-row__note">
                {auth?.connected
                  ? 'Connected — Mia can read Gmail and write to Sheets/Calendar.'
                  : auth?.configured
                    ? 'Not connected. Runs that touch Gmail or Sheets need this.'
                    : 'The agent has no Google OAuth client configured yet.'}
              </p>
            </div>
            <div className="setting-row__actions">
              {auth?.configured && (
                <a className="btn" href={agent.authStartUrl()}>
                  {auth.connected ? 'Reconnect' : 'Connect'}
                </a>
              )}
            </div>
          </div>
          <div className="setting-row setting-row--stacked">
            <div className="setting-row__name">Excluded websites</div>
            <p className="setting-row__note">
              Mia never observes accounts.google.com, login.microsoftonline.com, or any site you've added — that list
              lives in your browser's local extension storage, not in Kathy's backend or Poshitha's agent, so this
              dashboard has no way to read or edit it directly.
            </p>
            <p className="setting-row__note">
              Open the Mia panel in your browser toolbar to add or remove a site.
            </p>
          </div>
          <div className="setting-row setting-row--stacked">
            <div className="setting-row__name">Services</div>
            <dl className="service-list">
              <dt>Detection backend</dt>
              <dd>
                <code>{BACKEND_URL}</code>
                <span className={`status-chip status-chip--${backendError ? 'error' : 'done'}`}>
                  {backendError ? 'Unreachable' : 'Reachable'}
                </span>
              </dd>
              <dt>Agent</dt>
              <dd>
                <code>{AGENT_URL}</code>
                <span className={`status-chip status-chip--${agentError ? 'error' : 'done'}`}>
                  {agentError ? 'Unreachable' : 'Reachable'}
                </span>
              </dd>
            </dl>
            <p className="setting-row__note">
              Set with <code>VITE_MIA_BACKEND_URL</code> / <code>VITE_MIA_AGENT_URL</code> at build time.
            </p>
          </div>
        </Modal>
      )}
    </div>
  );
}
