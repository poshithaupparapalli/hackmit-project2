import { useState } from 'react';
import { MiaAvatar } from './MiaAvatar';
import {
  type MiaState,
  type MiaWorkflow,
  idleLine,
  thinkingLine,
  suggestingLine,
  confirmingLine,
  runningLine,
  successLine,
  failureLine,
} from './mia-personality';
import './mia-theme.css';

// Stand-in for the real suggestion object Kathy's /suggestions endpoint
// will eventually return. Match this shape to hers once the API contract
// is locked — swapping this for real data should be a one-line change.
const DEMO_WORKFLOW: MiaWorkflow = {
  trigger: '3 receipt emails from the last week',
  action: 'add a row to your Expenses sheet for each one',
  source: 'Gmail',
  target: 'Expenses sheet',
};

const STATES: MiaState[] = ['idle', 'thinking', 'suggesting', 'confirming', 'running', 'success', 'failure'];

function lineFor(state: MiaState): string {
  switch (state) {
    case 'idle':
      return idleLine();
    case 'thinking':
      return thinkingLine();
    case 'suggesting':
      return suggestingLine(DEMO_WORKFLOW);
    case 'confirming':
      return confirmingLine(DEMO_WORKFLOW);
    case 'running':
      return runningLine();
    case 'success':
      return successLine();
    case 'failure':
      return failureLine('Google didn\u2019t respond in time');
  }
}

export function MiaDemo() {
  const [state, setState] = useState<MiaState>('idle');

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        gap: 24,
        padding: 40,
        background: 'var(--mia-paper)',
        borderRadius: 20,
        maxWidth: 420,
        fontFamily: 'system-ui, sans-serif',
      }}
    >
      <MiaAvatar state={state} size={120} />
      <p style={{ color: 'var(--mia-ink)', fontSize: 16, textAlign: 'center', minHeight: 44, margin: 0 }}>
        {lineFor(state)}
      </p>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, justifyContent: 'center' }}>
        {STATES.map((s) => (
          <button
            key={s}
            onClick={() => setState(s)}
            style={{
              padding: '6px 14px',
              borderRadius: 999,
              border: state === s ? '2px solid var(--mia-competent)' : '1px solid var(--mia-ink-soft)',
              background: state === s ? 'var(--mia-paper-raised)' : 'transparent',
              color: 'var(--mia-ink)',
              cursor: 'pointer',
              fontSize: 13,
            }}
          >
            {s}
          </button>
        ))}
      </div>
    </div>
  );
}
