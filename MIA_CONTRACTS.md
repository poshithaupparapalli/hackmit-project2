# MIA — Integration Contracts (FROZEN — ping the team in chat before changing any of this)

These are the ONLY touchpoints between roles. Build against these and four people can
work in parallel without collisions.

## 1. Event schema (Anika produces → Kathy ingests)
type ScoutEvent = {
  t: number;                    // epoch ms
  type: "nav" | "click" | "edit" | "submit" | "copy" | "paste";
  host: string;
  path: string;
  title?: string;
  detail?: Record<string, string | number | boolean>;
  // detail examples:
  //   click:  { tag, role, label }
  //   edit:   { tag, type, name, len }     // len = char count, NEVER the value
  //   submit: { name, action, fields }
  //   paste:  { fromHost }                 // NEVER the content
};

## 2. Ingest endpoint (Anika calls → Kathy serves)
POST /v1/events/batch
  headers: Authorization: Bearer <INSTALL_TOKEN>
  body:    { events: ScoutEvent[] }         // send <= 250 per call
  200:     { accepted: number }

## 3. Suggestion schema (Kathy's LLM analyst produces → Ryan renders)
type Suggestion = {
  id: string;
  kind: "workflow" | "automation" | "rule";
  title: string;
  summary: string;
  evidence: string[];              // ["9 receipt emails opened", "8 sheet appends"]
  confidence: number;              // 0..1
  timeSavedPerWeekMinutes: number;
  workflowKey: string;             // maps to an agent workflow, e.g. "gmail_to_sheet"
  status: "proposed" | "accepted" | "dismissed" | "built";
};

## 4. Suggestions endpoints (Kathy serves → Ryan calls)
GET   /v1/suggestions            → { suggestions: Suggestion[] }
PATCH /v1/suggestions/:id        → body { status } → 200 { suggestion: Suggestion }

## 5. OAuth (Ryan's page initiates → Kathy stores → Poshitha's agent uses)
GET  /v1/auth/google/start       → redirects user to Google consent
GET  /v1/auth/google/callback    → stores token SERVER-SIDE, redirects back to page
GET  /v1/auth/status             → { connected: boolean, email?: string }
  The agent reads the stored token server-side. The token NEVER touches the frontend.
  SETUP NOTE (Poshitha + Ryan, first hour): create Google Cloud OAuth creds, enable
  Gmail API + Sheets API, add your demo Google account as a TEST USER, and get through
  the "unverified app" consent screen TONIGHT. This is the #1 risk item.

## 6. Agent run — WORKFLOW-AGNOSTIC contract (Ryan's "Run" calls → Poshitha executes)
POST /v1/workflows/:workflowKey/run
  body:   { suggestionId: string }
  200:    { runId: string }
GET  /v1/workflows/runs/:runId   → live status for the UI to poll:
  {
    runId: string;
    workflowKey: string;
    status: "running" | "done" | "error" | "needs_approval";
    steps: { label: string; state: "pending"|"running"|"done"|"error" }[];
    result?: Record<string, any>;   // e.g. { rowsAppended: 3, sheetUrl: "..." }
    error?: string;
  }
POST /v1/workflows/runs/:runId/approve   → resumes a run paused at needs_approval

  ^ THIS contract is what lets Poshitha swap workflows freely. As long as the agent
  takes workflowKey + suggestionId and reports steps[]/status/result in this shape,
  Ryan's UI and Kathy's pipeline never change when Poshitha changes what the agent
  does. Poshitha can try several workflows before midnight; the contract stays fixed.

## 7. Approval boundary (safety — must be visible in UI)
If a run would send / submit / purchase / delete, the agent returns status
"needs_approval" and waits. Ryan's UI shows an Approve button → calls the approve
endpoint. For the receipt demo (read + append) this may not trigger, but the mechanism
must EXIST and be SHOWN — it's part of the trust pitch.

## 8. FALLBACK DATASET + DEMO MODE (Owner: KATHY; Poshitha supplies one real agent result)
Purpose: run the ENTIRE demo end to end even if venue wifi / live capture / Google API
fails at the judging table. Always try live first; fall back to this if anything hangs.

Two artifacts:
  a) Pre-recorded events file (JSONL): one real captured run of the receipt workflow,
     saved to disk. Lets the pattern miner produce the suggestion WITHOUT live capture.
  b) Canned agent result: one real successful agent run frozen to disk — the steps[],
     status:"done", and result{} exactly as the live agent would return them.
     (Poshitha runs the real agent once, hands Kathy that output to freeze.)

Demo-mode toggle (backend, one flag — e.g. env var DEMO_MODE=true):
  - When ON, the backend serves the canned suggestion (from 8a via the miner) and the
    canned run result (from 8b) instead of calling live capture / live Google APIs.
  - Every teammate's part runs unchanged off the same endpoints; only the data source
    behind them switches. No frontend or extension code changes to use demo mode.
Build this ONCE the live happy path works. It is non-negotiable insurance.

## Freeze order (first 30 min, together, before coding)
1. Confirm schemas 1, 3.
2. Confirm endpoints 2, 4, 5, 6.
3. Confirm the ONE workflowKey for the demo (default "gmail_to_sheet"; Poshitha locks
   by MIDNIGHT).
4. Confirm privacy rules (from the context file) and the DEMO_MODE flag name.
Then everyone builds independently against these.
