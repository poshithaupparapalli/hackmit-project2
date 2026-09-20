# MIA — Frozen Integration Contract (v1)
Do not rename fields without pinging both sides in team chat.
Detection half = proven from the Mana prototype. Execution half = new (agent + OAuth).
The seam between them is `workflowKey`.

====================================================================
PART A — DETECTION  (Anika = extension, Kathy = backend pipeline)
Proven in the Mana prototype. Build straight off this.
====================================================================

## A1. Architecture (detection)
content.js → service-worker.js → POST /v1/events/batch → event DB
→ deterministic pattern miner → LLM analyst → suggestions API → dashboard/workflows page

## A2. Canonical event schema
All timestamps are UTC Unix milliseconds. IDs are ULID/UUID.

type EventType =
  | "nav" | "click" | "edit" | "submit" | "copy" | "paste"
  | "shortcut" | "tabopen" | "tabclose" | "scroll" | "focus";

interface ScoutEvent {
  schemaVersion: 1;
  id: string;
  installId: string;
  sessionId: string;
  timestamp: number;      // epoch ms — canonical field name, NOT "t"
  sequence: number;
  tabId: number;
  frameId: number;
  type: EventType;
  host: string;
  path: string;
  title?: string;
  detail?: Record<string, string | number | boolean | null>;
}

## A3. Event detail fields
nav:      { referrerHost }
click:    { tag, role, label, hrefHost, hrefPath }
edit:     { tag, inputType, name, length }   // length = char count, NEVER the value
                                             // emit once after debounce/blur/change, not per keystroke
submit:   { name, actionHost, actionPath, fieldCount, via }  // via: "button"|"enter"|"unknown"
copy:     { length, wordCount }
paste:    { length, targetTag, targetName }  // NEVER the content
shortcut: { key }                            // e.g. "Ctrl+K"
scroll:   { depth }                          // only at 25/50/75/100
focus:    { visible }

## A4. Mandatory privacy rules (load-bearing for the pitch — enforce in code)
NEVER collect: field values, password events (not even length), clipboard contents,
query strings, URL fragments, auth tokens, cookies, full page HTML, screenshots
(by default), individual keystrokes.

sanitizeUrl(value): return { host: hostname.toLowerCase(), path: pathname }  // strip query + fragment
Drop event entirely when: element is HTMLInputElement && element.type === "password"
Truncate: label <=80, title <=160, path <=500, detail JSON <=2KB
UI must ALWAYS show: live "observing" indicator, pause button, excluded-domains list.

## A5. Batch ingestion API
POST /v1/events/batch
  Authorization: Bearer <install-token>
  body:
    interface EventBatchRequest {
      schemaVersion: 1; installId: string; sentAt: number; events: ScoutEvent[];  // <=250
    }
  response:
    interface EventBatchResponse {
      accepted: string[];
      rejected: Array<{ id: string; reason: string }>;
      serverTime: number;
    }
Backend must be idempotent on installId + event.id (retry must not duplicate).

## A6. Extension queue requirements
Store unsent events in chrome.storage.local.
Max queue 5000. Batch 250. Normal flush every 30–60s. Immediate flush at 100 queued.
Retry with exponential backoff. Only remove IDs returned in `accepted`.
Must keep working while backend is offline.

## A7. Settings schema
interface ScoutSettings {
  paused: boolean; excludedDomains: string[]; windowDays: number;
  minNewEvents: number; analyzeEveryMinutes: number;
}
defaults: {
  paused: false,
  excludedDomains: ["accounts.google.com", "login.microsoftonline.com"],
  windowDays: 7, minNewEvents: 25, analyzeEveryMinutes: 30
}
Excluded domains match host + all subdomains.

## A8. Pattern digest schema
interface PatternDigest {
  computedAt: number; eventCount: number; windowDays: number;
  hosts: Array<{ host; events; navigations; minutes; days; topPaths: string[]; topTitles: string[] }>;
  transitions: Array<{ path: string[]; count: number }>;
  repeatedForms: Array<{ host; path; form; count; days }>;
  repeatedFields: Array<{ host; field; count }>;
  copyPaste: Array<{ from; to; count }>;
  sessions: Array<{ start; end; events; hosts: string[] }>;
}
New session starts after 15 min without activity.

## A9. Suggestion schema  ← STITCH: added `workflowKey`
type SuggestionKind = "workflow" | "automation" | "rule";
type SuggestionStatus = "proposed" | "accepted" | "dismissed" | "built";

interface Suggestion {
  id: string;
  kind: SuggestionKind;
  title: string;                    // <=60 chars
  summary: string;
  evidence: string[];               // 1–3 concrete observations from real events
  steps: string[];                  // required for workflows
  trigger: string;                  // required for rules
  action: string;
  buildPrompt: string;
  workflowKey: string | null;       // ← SEAM: which agent workflow this maps to,
                                     //   e.g. "gmail_to_sheet". null if not executable yet.
  confidence: number;               // 0..1
  timeSavedPerWeekMinutes: number;
  status: SuggestionStatus;
  createdAt: number;
  updatedAt: number;
}
Rules: grounded in real evidence; no duplicates of existing suggestions.

## A10. Suggestion + status API
GET   /v1/suggestions
PATCH /v1/suggestions/:id      body { status }
POST  /v1/analyze             → { queued: true }
GET   /v1/status              → { observerOnline, paused, lastEventAt, lastAnalysisAt, newEventsPending }

## A11. Analyzer rules
Deterministic mining every 5 min. Invoke LLM when newEventsPending>=25 AND minutes-since-last>=30,
or when /v1/analyze is called. LLM receives: PatternDigest + compact recent trace +
existing suggestion titles/statuses + instructions to return 0–4 grounded suggestions.
Validate model output against Suggestion schema before saving.

====================================================================
PART B — EXECUTION  (Poshitha = agent, Ryan = frontend + OAuth pairing)
NEW. Not in the Mana prototype. This is the agent that actually DOES the workflow.
====================================================================

## B1. Where the agent lives
Agent runs on the BACKEND. Extension is eyes-only. Agent acts via Google APIs
(Gmail read + Sheets append), NOT by driving the page DOM.
Agent = LLM brain + hand-built tools. Tonight's tools: read_gmail(), append_to_sheet().
The LLM decides how to use them; capability = the tools we built.

## B2. OAuth (Ryan's page initiates → Kathy stores → Poshitha's agent uses)
GET /v1/auth/google/start      → redirect to Google consent
GET /v1/auth/google/callback   → store token SERVER-SIDE, redirect back to page
GET /v1/auth/status            → { connected: boolean, email?: string }
Token never touches the frontend. Agent reads it server-side.
SETUP (Poshitha + Ryan, FIRST HOUR — #1 risk): create Google Cloud OAuth creds,
enable Gmail API + Sheets API, add demo account as TEST USER, clear the
"unverified app" consent screen TONIGHT.

## B3. Agent run — WORKFLOW-AGNOSTIC contract (Ryan "Run" → Poshitha executes)
POST /v1/workflows/:workflowKey/run     body { suggestionId }  → { runId }
GET  /v1/workflows/runs/:runId →
  {
    runId: string;
    workflowKey: string;
    status: "running" | "done" | "error" | "needs_approval";
    steps: { label: string; state: "pending"|"running"|"done"|"error" }[];
    result?: Record<string, any>;   // e.g. { rowsAppended: 3, sheetUrl: "..." }
    error?: string;
  }
POST /v1/workflows/runs/:runId/approve  → resumes a run paused at needs_approval

^ As long as the agent takes workflowKey + suggestionId and reports this steps[]/status/
result shape, Ryan's UI and Kathy's pipeline never change when Poshitha swaps what the
agent does. Poshitha may try several workflows before midnight; this contract stays fixed.

## B4. Approval boundary (safety — must be visible in UI)
If a run would send/submit/purchase/delete → status "needs_approval", agent waits,
UI shows Approve → approve endpoint. Receipt demo (read+append) may not trigger it,
but the mechanism must EXIST and be SHOWN — it's part of the trust pitch.

## B5. Fallback dataset + demo mode  (Owner: KATHY; Poshitha supplies one real run)
Purpose: run the WHOLE demo end to end even if wifi / live capture / Google API dies at
the table. Always try live first; fall back if anything hangs.
Artifacts:
  a) Pre-recorded events JSONL — one real captured receipt run, so the miner produces
     the suggestion WITHOUT live capture.
  b) Canned agent result — one real successful run frozen to disk: exact steps[],
     status:"done", result{} the live agent would return. (Poshitha runs it once → hands to Kathy.)
Demo-mode toggle (backend env var DEMO_MODE=true):
  when ON, backend serves the canned suggestion (via miner from B5a) and canned run
  result (B5b) instead of live capture / live Google calls. No frontend or extension
  code changes to use it. Build once the live happy path works. Non-negotiable insurance.

====================================================================
PART C — OWNERSHIP, DEMO, TESTS
====================================================================

## C1. Team ownership
Anika  — extension: manifest.json, content.js, service-worker.js, sanitization, pause,
         excluded domains, durable queue, batch client. (Part A2–A7)
Kathy  — backend: ingestion, auth token storage, event DB, pattern miner, LLM analyst,
         suggestions API, fallback dataset + demo mode. NO UI. (Part A5–A11, B5)
Poshitha — agent runner + Google API tools + run-status state machine. Owns the ONE
         workflow. Co-owns OAuth. (Part B1–B4)
Ryan   — ALL frontend: workflows web page (login, connect Google, see suggestions,
         Run, watch run, approve) + any dashboard, calling the endpoints above.
         Co-owns OAuth setup. NO backend logic.
Seam: `workflowKey` connects a Suggestion (A9) to an agent run (B3).
Rule: Kathy writes no UI; Ryan writes no backend logic; don't both build the page.

## C2. Demo success condition  ← STITCH: Swag Labs REPLACED with receipts
Target workflow: Gmail → Google Sheets receipt/expense loop (workflowKey "gmail_to_sheet").
After a few repeats, MIA detects:
  open receipt email → copy amount → switch to sheet → append row  (repeated)
It proposes (grounded in real counts):
  "Log your receipt totals into the expenses sheet automatically."
Card shows evidence counts, confidence, time saved; user can inspect / accept / dismiss.
On Run: agent reads the receipt email, extracts the amount, appends a row to the sheet,
run-status shows each step completing live. (Old Swag Labs demo is dropped.)

## C3. Freeze order (first 30 min, together, before coding)
1. Confirm event schema (A2) + detail fields (A3) + privacy (A4).
2. Confirm ingest (A5) + suggestions (A9–A10).
3. Confirm the ONE workflowKey = "gmail_to_sheet" (Poshitha locks by MIDNIGHT).
4. Confirm DEMO_MODE flag name + fallback owner (Kathy).
Then build independently against these.

## C4. Acceptance tests (system is done only when these pass)
Detection (from Mana, kept):
 1. Reposting a batch does not duplicate events.
 2. Events survive service-worker suspension.
 3. Events stay queued while backend offline.
 4. Pausing stops collection immediately.
 5. Excluded domains produce no events.
 6. Password fields produce no events.
 7. URLs contain no query strings or fragments.
 8. Clipboard contents never appear in storage.
 9. A few repeated receipt runs produce a grounded suggestion.   ← was Swag Labs
10. Every suggestion includes evidence from stored events.
11. Dismissing and restoring a suggestion persists.
Execution (new):
12. No automation performs an external action without user approval.
13. OAuth yields a server-side token that can read Gmail AND append to Sheets.
14. A real run appends the correct row and reports status "done" with result{}.
15. With DEMO_MODE=true, the full demo runs end to end using canned data (no network).
