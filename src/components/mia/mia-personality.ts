/**
 * MIA — Personality & Voice
 * ===================================================================
 * RULE OF THUMB: whimsy lives in the DECORATION (idle, thinking,
 * running, success). Seriousness lives in the MOMENTS THAT MATTER
 * (confirming, failure) — that's where trust is won or lost, so no
 * jokes, no fluff, no hedging, no exclamation points.
 *
 * MIA describes what it SAW, never what it thinks about the person.
 *   "I noticed you copied 3 amounts into that email"   <- yes
 *   "You seem disorganized with expenses"               <- never
 *
 * Every confirming/failure line must be able to stand alone as an
 * honest, complete sentence — a judge or a nervous first-time user
 * should be able to read ONLY that line and know exactly what will
 * happen or what happened.
 * ===================================================================
 */

export type MiaState =
  | 'idle'
  | 'thinking'
  | 'suggesting'
  | 'confirming'
  | 'running'
  | 'success'
  | 'failure';

export interface MiaWorkflow {
  /** The pattern MIA noticed, in plain language. e.g. "3 receipt emails from the last week" */
  trigger: string;
  /** The action being offered/run, in plain language. e.g. "add a row to your Expenses sheet for each one" */
  action: string;
  /** Where MIA reads from. e.g. "Gmail" */
  source?: string;
  /** Where MIA writes to. e.g. "Expenses sheet" */
  target?: string;
}

/** Light variation keeps repeat visits from feeling robotic — never used for confirming/failure. */
const IDLE_LINES = [
  'Keeping an eye on things.',
  'Just watching — not touching anything.',
  'Here if you need me.',
  'Quietly taking notes.',
];

const THINKING_LINES = [
  'Noticing a pattern…',
  'Piecing something together…',
  'This looks familiar…',
];

const RUNNING_LINES = [
  'On it.',
  'Working through this now.',
  'Give me just a second.',
];

const SUCCESS_LINES = ['Done — that\u2019s logged.', 'All set.', 'Added it for you.'];

function pick(lines: string[]): string {
  return lines[Math.floor(Math.random() * lines.length)];
}

export function idleLine(): string {
  return pick(IDLE_LINES);
}

export function thinkingLine(): string {
  return pick(THINKING_LINES);
}

/** Warm but factual. States the pattern and the offer — nothing sold, nothing implied. */
export function suggestingLine(w: MiaWorkflow): string {
  return `I noticed ${w.trigger}. Want me to ${w.action}?`;
}

/**
 * Short teaser shown above the suggestion itself (the popup hero), where
 * there isn't room for the full line. Still describes what MIA SAW, never
 * the person. Not randomized — the detail belongs to suggestingLine().
 */
export function noticedLine(): string {
  return 'I noticed something.';
}

/**
 * SERIOUS. No whimsy. This is the trust-critical moment — always states
 * source, action, and scope explicitly. Never randomized: the whole team
 * and every judge sees exactly this sentence, every time.
 */
export function confirmingLine(w: MiaWorkflow): string {
  const sourcePart = w.source ? `read from ${w.source} and ` : '';
  return `I\u2019ll ${sourcePart}${w.action}. Nothing else changes.`;
}

export function runningLine(): string {
  return pick(RUNNING_LINES);
}

export function successLine(): string {
  return pick(SUCCESS_LINES);
}

/**
 * PLAIN. No apology, no self-blame, no whimsy. States what happened and
 * that nothing was changed, since that's the fact that matters most to
 * someone who just watched an AI touch their inbox or spreadsheet.
 */
export function failureLine(reason?: string): string {
  const detail = reason ? ` ${reason}.` : '';
  return `That didn\u2019t go through.${detail} Nothing was changed.`;
}
