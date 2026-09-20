# MIA — Frozen Integration Contract (v1.1)

**Do not rename fields or change endpoint shapes without pinging both sides in team chat.**

Detection half = proven from the Mana prototype and ported into the Chrome extension.  
Execution half = new agent + OAuth work.

The seam between them is `workflowKey`.

Core product rule:

> **Mia never initiates an automation on her own.**  
> Mia observes → proposes → user accepts, dismisses, or edits → user explicitly runs the workflow.

---

# PART A — DETECTION

**Owners:**  
**Anika** = Chrome extension + extension UI  
**Kathy** = backend detection pipeline

## A1. Architecture

```text
content.js
    ↓
service-worker.js
    ↓
durable local queue
    ↓
POST /v1/events/batch
    ↓
event DB
    ↓
deterministic pattern miner
    ↓
LLM analyst
    ↓
suggestions API
    ↓
Mia extension side panel / workflows page
```

The extension observes and sanitizes.

The backend stores events, detects patterns, infers task semantics, and generates grounded suggestions.

---

## A2. Canonical event schema

All timestamps are UTC Unix milliseconds.

IDs are ULID/UUID.

```ts
type EventType =
  | "nav"
  | "click"
  | "edit"
  | "submit"
  | "copy"
  | "paste"
  | "shortcut"
  | "tabopen"
  | "tabclose"
  | "scroll"
  | "focus";

interface MiaEvent {
  schemaVersion: 1;

  id: string;
  installId: string;
  sessionId: string;

  timestamp: number;
  sequence: number;

  // Added by service-worker.js from Chrome's message sender.
  // content.js does NOT generate these.
  tabId: number;
  frameId: number;

  type: EventType;

  host: string;
  path: string;
  title?: string;

  detail?: Record<string, string | number | boolean | null>;

  // Small semantic hints about WHAT the user is interacting with.
  // Never use this for arbitrary page text.
  context?: {
    // Optional bounded task identity. These fields extend context without
    // changing schemaVersion; they contain labels/titles, never page bodies.
    pageTitle?: string;
    itemTitle?: string;
    sectionLabel?: string;
    formLabel?: string;
    targetLabel?: string;
    nearbyText?: string;
    semanticType?: string;
  };
}
```

### Responsibility boundary

`content.js` creates the observation.

`service-worker.js` attaches:

```text
tabId
frameId
installId
```

before putting the canonical `MiaEvent` into the queue.

---

## A3. Event detail fields

```text
nav:
  { referrerHost }

click:
  { tag, role, label, hrefHost, hrefPath }

edit:
  { tag, inputType, name, length }

submit:
  { name, actionHost, actionPath, fieldCount, via }

copy:
  { length, wordCount }

paste:
  { length, targetTag, targetName }

shortcut:
  { key }

scroll:
  { depth }

focus:
  { visible }
```

### Specific rules

For `edit`:

```text
length = character count
NEVER actual value
emit after debounce / blur / change
NEVER emit every keystroke
```

For `submit`:

```ts
via: "button" | "enter" | "unknown"
```

For `scroll`:

Only emit at approximately:

```text
25%
50%
75%
100%
```

---

## A4. Semantic context

The extension may attach a small amount of semantic context so the backend can infer what task the user is performing.

Example:

```json
{
  "type": "click",
  "host": "calendar.google.com",
  "path": "/calendar/u/0/r",
  "detail": {
    "tag": "BUTTON",
    "role": "button",
    "label": "Save"
  },
  "context": {
    "sectionLabel": "Event details",
    "formLabel": "Create event",
    "targetLabel": "Save"
  }
}
```

Another example:

```json
{
  "type": "copy",
  "host": "mail.google.com",
  "detail": {
    "length": 6,
    "wordCount": 1
  },
  "context": {
    "sectionLabel": "Receipt",
    "targetLabel": "Total"
  }
}
```

Mia may know that the user copied a **receipt total**.

Mia must NOT know that the total was **$42.18**.

### Context limits

```text
pageTitle    <= 200 chars
itemTitle    <= 200 chars
sectionLabel <= 120 chars
formLabel    <= 120 chars
targetLabel  <= 120 chars
nearbyText   <= 200 chars
semanticType <= 32 chars
```

These optional context fields are a backward-compatible v1 extension requested
for task-semantic understanding. They may contain bounded visible titles and
labels, but never raw form values, email bodies, spreadsheet cell contents,
clipboard contents, full-page text, tokens, or screenshots.

Semantic context should come from things such as:

```text
aria-label
form labels
input labels
nearest heading
button text
section heading
placeholder
role
```

Do NOT populate semantic context with arbitrary surrounding page text.

---

## A5. Mandatory privacy rules

These are enforced in code.

### NEVER collect

```text
field values
password events — not even length
clipboard contents
query strings
URL fragments
auth tokens
cookies
full page HTML
screenshots by default
individual keystrokes
```

### URL sanitization

```ts
sanitizeUrl(value):
  return {
    host: hostname.toLowerCase(),
    path: pathname
  }
```

Always strip:

```text
?query=params
#fragments
```

### Password fields

Drop the event entirely when:

```ts
element instanceof HTMLInputElement &&
element.type === "password"
```

### Truncation

```text
label              <= 80 chars
title              <= 160 chars
path               <= 500 chars
semantic labels    <= 80 chars each
detail JSON        <= 2 KB
```

### UI requirements

The extension UI must ALWAYS make observation state visible.

It must provide:

```text
Observing / Paused indicator
Pause / Resume button
Excluded domains list
```

---

## A6. Excluded domains

Excluded domains produce **zero observation events**.

Domain matching applies to:

```text
host
+
all subdomains
```

Example:

```text
example.com
```

also excludes:

```text
mail.example.com
accounts.example.com
foo.bar.example.com
```

Default excluded domains:

```json
[
  "accounts.google.com",
  "login.microsoftonline.com"
]
```

Users may add or remove excluded domains.

The extension checks exclusions **before constructing or storing an event**.

---

## A7. Extension installation identity

On first install, the extension requests an installation identity.

```text
POST /v1/install
```

Response:

```ts
interface InstallResponse {
  installId: string;
  installToken: string;
}
```

The extension stores both in:

```text
chrome.storage.local
```

All event-ingestion requests use:

```text
Authorization: Bearer <installToken>
```

Rules:

```text
installToken is never sent to content.js
installToken is never logged
installToken is only used by service-worker.js
```

If extension storage is cleared, a new installation identity may be created.

---

## A8. Batch ingestion API

```text
POST /v1/events/batch
Authorization: Bearer <installToken>
```

Request:

```ts
interface EventBatchRequest {
  schemaVersion: 1;
  installId: string;
  sentAt: number;
  events: MiaEvent[];
}
```

Maximum:

```text
250 events / request
```

Response:

```ts
interface EventBatchResponse {
  accepted: string[];

  rejected: Array<{
    id: string;
    reason: string;
  }>;

  serverTime: number;
}
```

Backend must be idempotent on:

```text
installId + event.id
```

Retrying a batch must never duplicate events.

---

## A9. Extension queue requirements

Unsent events are stored in:

```text
chrome.storage.local
```

### Queue limits

Maximum:

```text
5,000 events
OR
5 MB serialized

whichever comes first
```

### Flushing

Normal flush:

```text
every 30–60 seconds
```

Use an extension alarm/event rather than assuming the service worker remains continuously alive.

Immediate flush:

```text
>= 100 queued events
```

Maximum batch:

```text
250 events
```

### Failure behavior

On network/backend failure:

```text
keep events locally
retry with exponential backoff
```

Only remove events whose IDs appear in:

```text
response.accepted
```

Rejected events may be logged locally by ID + reason for debugging, but sensitive event contents must not be logged.

The queue must continue functioning when the backend is offline.

The queue must survive service-worker suspension/restart.

---

## A10. Settings schema

```ts
interface MiaSettings {
  paused: boolean;
  excludedDomains: string[];

  windowDays: number;
  minNewEvents: number;
  analyzeEveryMinutes: number;
}
```

Defaults:

```json
{
  "paused": false,
  "excludedDomains": [
    "accounts.google.com",
    "login.microsoftonline.com"
  ],
  "windowDays": 7,
  "minNewEvents": 25,
  "analyzeEveryMinutes": 30
}
```

Excluded domains match host + all subdomains.

When:

```text
paused = true
```

`content.js` must stop producing observations immediately.

---

## A11. Pattern digest schema

```ts
interface PatternDigest {
  computedAt: number;
  eventCount: number;
  windowDays: number;

  hosts: Array<{
    host: string;
    events: number;
    navigations: number;
    minutes: number;
    days: number;
    topPaths: string[];
    topTitles: string[];
  }>;

  transitions: Array<{
    path: string[];
    count: number;
  }>;

  repeatedForms: Array<{
    host: string;
    path: string;
    form: string;
    count: number;
    days: number;
  }>;

  repeatedFields: Array<{
    host: string;
    field: string;
    count: number;
  }>;

  copyPaste: Array<{
    from: string;
    to: string;
    count: number;
  }>;

  sessions: Array<{
    start: number;
    end: number;
    events: number;
    hosts: string[];
  }>;
}
```

New session starts after:

```text
15 minutes without activity
```

---

## A12. Controlled workflow keys

For v1, executable workflows are a controlled set.

```ts
type WorkflowKey =
  | "gmail_to_sheet";
```

Suggestions use:

```ts
workflowKey: WorkflowKey | null;
```

The LLM does **not** invent arbitrary workflow keys.

It may infer that a suggestion resembles an executable workflow, but deterministic backend validation decides whether that `workflowKey` actually exists.

Example:

```text
Detected workflow:
Gmail receipt → Google Sheet

Known executable workflow:
gmail_to_sheet

→ workflowKey = "gmail_to_sheet"
```

Unknown workflow:

```text
Detected workflow:
Book weekly tennis court

No corresponding agent tool exists.

→ workflowKey = null
```

---

## A13. Suggestion schema

```ts
type SuggestionKind =
  | "workflow"
  | "automation"
  | "rule";

type SuggestionStatus =
  | "proposed"
  | "accepted"
  | "dismissed"
  | "built";

interface Suggestion {
  id: string;

  kind: SuggestionKind;

  title: string;
  summary: string;

  evidence: string[];

  steps: string[];

  trigger: string;
  action: string;

  buildPrompt: string;

  workflowKey: WorkflowKey | null;

  confidence: number;
  timeSavedPerWeekMinutes: number;

  status: SuggestionStatus;

  createdAt: number;
  updatedAt: number;
}
```

Constraints:

```text
title <= 60 chars
confidence = 0..1
evidence = 1–3 concrete observations
steps required for workflow suggestions
trigger required for rule suggestions
```

Suggestions must be grounded in real evidence.

Do not create duplicates of existing suggestions.

---

## A14. Suggestion APIs

```text
GET /v1/suggestions
```

Returns current suggestions.

```text
PATCH /v1/suggestions/:id
```

Body:

```ts
{
  status: SuggestionStatus;
}
```

Used for simple status changes/restoring previous suggestions.

### User feedback

```text
POST /v1/suggestions/:id/feedback
```

Body:

```ts
interface SuggestionFeedbackRequest {
  decision: "accept" | "dismiss" | "edit";
  userEdits?: string;
}
```

Examples:

```json
{
  "decision": "accept"
}
```

```json
{
  "decision": "dismiss"
}
```

```json
{
  "decision": "edit",
  "userEdits": "Only do this for reimbursement receipts over $25."
}
```

Backend persists feedback.

Edits become evidence available to future analysis.

An edit may eventually create or modify a candidate rule.

### Other detection endpoints

```text
POST /v1/analyze
```

Response:

```json
{
  "queued": true
}
```

```text
GET /v1/status
```

Response:

```ts
{
  observerOnline: boolean;
  paused: boolean;

  lastEventAt: number | null;
  lastAnalysisAt: number | null;

  newEventsPending: number;
}
```

---

## A15. Analyzer rules

Run deterministic mining approximately every:

```text
5 minutes
```

Invoke LLM analysis when:

```text
newEventsPending >= 25

AND

minutesSinceLastAnalysis >= 30
```

OR:

```text
POST /v1/analyze
```

is called.

The LLM receives:

```text
PatternDigest
+
compact recent event trace
+
semantic context
+
existing suggestion titles/statuses
+
relevant user feedback/edits
```

The analyst returns:

```text
0–4 grounded suggestions
```

Empty output is valid when evidence is weak.

Validate all model output against the `Suggestion` schema before saving.

---

# PART B — EXECUTION

**Owners:**  
**Poshitha** = agent runner + tools  
**Ryan** = web frontend + OAuth  
**Kathy** = server-side token storage

Execution is NEW.

It is separate from Mia's observation system.

---

## B1. Where the agent lives

The execution agent runs on the **backend**.

The extension is eyes + user interaction only.

For the demo, execution happens through Google APIs rather than replaying browser DOM actions.

Tonight's tools:

```text
read_gmail()
append_to_sheet()
```

Agent:

```text
LLM reasoning
+
hand-built tools
```

The model can only perform capabilities exposed through those tools.

---

## B2. Core execution rule

### Mia NEVER starts an automation automatically.

The flow is:

```text
Mia observes
    ↓
Mia detects pattern
    ↓
Mia proposes workflow
    ↓
User chooses:
    YES / NO / EDIT
    ↓
If accepted:
workflow becomes available
    ↓
User explicitly clicks RUN
    ↓
Agent may begin execution
```

Accepting a suggestion is **not permission to execute it**.

Clicking `Run` authorizes the agent to perform the displayed workflow plan.

---

## B3. OAuth

Ryan's page initiates OAuth.

Kathy stores tokens.

Poshitha's agent consumes them.

Endpoints:

```text
GET /v1/auth/google/start
```

Redirect to Google consent.

```text
GET /v1/auth/google/callback
```

Store token server-side.

Redirect back to frontend.

```text
GET /v1/auth/status
```

Response:

```ts
{
  connected: boolean;
  email?: string;
}
```

Google OAuth tokens never touch the frontend.

### First-hour setup

Poshitha + Ryan:

```text
Create Google Cloud OAuth credentials
Enable Gmail API
Enable Sheets API
Add demo account as TEST USER
Complete the development consent flow
```

Treat this as an early integration risk.

---

## B4. Agent run contract

User explicitly clicks `Run`.

Frontend calls:

```text
POST /v1/workflows/:workflowKey/run
```

Body:

```ts
{
  suggestionId: string;
}
```

Response:

```ts
{
  runId: string;
}
```

Status:

```text
GET /v1/workflows/runs/:runId
```

Response:

```ts
interface WorkflowRun {
  runId: string;

  workflowKey: WorkflowKey;

  status:
    | "running"
    | "done"
    | "error"
    | "needs_approval";

  steps: Array<{
    label: string;

    state:
      | "pending"
      | "running"
      | "done"
      | "error";
  }>;

  result?: Record<string, any>;

  error?: string;

  approvalRequest?: {
    title: string;
    description: string;
  };
}
```

Example result:

```json
{
  "rowsAppended": 3,
  "sheetUrl": "..."
}
```

As long as the agent accepts:

```text
workflowKey + suggestionId
```

and returns this run shape, the frontend and detection pipeline do not change when agent implementation changes.

---

## B5. Approval boundary

There are **two different approvals**.

### Approval 1 — Run

The user explicitly clicks:

```text
Run
```

This authorizes the displayed workflow.

Nothing runs merely because Mia detected or accepted a pattern.

### Approval 2 — Unexpected consequential action

If the running workflow encounters a consequential action that was **not clearly included in the plan the user approved**, pause.

Examples:

```text
send
submit
purchase
delete
unexpected external write
```

Agent returns:

```text
status = "needs_approval"
```

UI displays:

```text
Mia needs approval

[description of action]

[Approve] [Cancel]
```

Approve endpoint:

```text
POST /v1/workflows/runs/:runId/approve
```

The agent then resumes.

For the receipt demo, if the user clicked Run on a plan that explicitly says:

> Read receipt email → append receipt to expense sheet

the Sheet append is already within the authorized plan.

It does not require a second approval.

---

## B6. Fallback dataset + demo mode

**Owner:** Kathy  
**Poshitha:** supplies one successful real run

Purpose:

The entire demo must still work if:

```text
Wi-Fi fails
live capture fails
Google API fails
OAuth hangs
backend dependency fails
```

Always attempt live first.

Fallback only when necessary.

### Artifact A — prerecorded events

One real captured receipt workflow.

The miner should produce the suggestion from these events without live capture.

### Artifact B — canned agent result

One successful real agent run frozen to disk.

It must use exactly the same:

```text
steps[]
status
result{}
```

shape as a live run.

### Demo mode

Backend environment variable:

```text
DEMO_MODE=true
```

When enabled:

```text
detection → prerecorded event dataset
execution → canned successful run
```

No extension or frontend code changes.

Build demo mode only after the live happy path works.

This is non-negotiable demo insurance.

---

## B7. Workflow Registry

**Owner:** Poshitha (agent tools + statuses). Kathy tags each suggestion with a
`workflowKey` from this table (or `null` if no matching workflow exists).

MIA is designed to support **multiple** agent workflows, not just one. Each row
below is a distinct executable workflow. Adding a workflow means adding its
tool(s) on the agent side and (for a new key) extending the controlled
`WorkflowKey` set — see the coordination note below.

`status` values: `planned` | `building` | `working`.

| Priority | workflowKey | Description | Scopes / auth | Status |
|----------|-------------|-------------|---------------|--------|
| 1 | `gmail_to_sheet` | Read a receipt/expense email, append a row to a Sheet. | `gmail.readonly` + `spreadsheets` | building |
| 2 | `email_to_calendar` | Read an email, create a Google Calendar event from it. | `gmail.readonly` + `calendar.events` | planned |
| 3 | `inbox_triage` | Read unread emails, categorize, draft replies. Draft only; **sending requires approval via B5**. | `gmail.readonly` (+ `gmail.compose` if drafting) | planned |
| 4 | `slack_post` | Post / summarize a message to Slack. | Slack OAuth (separate from Google) | planned |
| 5 | `notion_file` | File notes / tasks into a Notion database. | Notion token | planned |
| 6 | `email_to_calendar_to_slack` | Multi-step chain across apps (email → calendar → Slack). | Google + Slack | planned |

Priority 6 (multi-app chain) is only attempted **after** at least one single-app
workflow is fully working.

### The run contract is workflow-agnostic

The run contract (**B4** — `POST /v1/workflows/:workflowKey/run`,
`GET /v1/workflows/runs/:runId`, `POST /v1/workflows/runs/:runId/approve`)
already supports **all** of these workflows as-is. It accepts a `workflowKey`
and returns the frozen run shape `{ runId, workflowKey, status, steps[], result,
error }`. Nothing about it is specific to one workflow.

Therefore, adding a workflow **does not change**:

```text
the Chrome extension
the backend detection pipeline
the web frontend
```

Each new workflow needs only:

```text
1. its own hand-built tool(s) on the agent side
2. a workflowKey tag on the suggestion (Kathy sets it; null if no match)
```

**Coordination note:** the executable set is still controlled (A12). The
`WorkflowKey` literal currently allows only `gmail_to_sheet`. Promoting a
registry row from `planned` to `building`/`working` requires Kathy to add that
key to the `WorkflowKey` literal + analyst mapping. This is an additive change,
but per the freeze rule it must be pinged to both sides — it is not silent.

### BUILD DISCIPLINE (non-negotiable)

```text
Build workflows in strict priority order.
Each workflow must fully work end-to-end before the next is started.
A workflow that is not yet `working` is a VISION-SLIDE item, not a demo item.
```

The demo shows the **working** workflows plus the agent choosing the right tool
per detected pattern. It never shows a half-built workflow as if it were real.

---

# PART C — FRONTEND / EXTENSION UI

## C1. Extension side panel

**Owner: Anika**

Anika owns:

```text
manifest.json
content.js
service-worker.js

sidepanel.html
sidepanel.js
sidepanel.css

sanitization
semantic context extraction
pause/resume
excluded domains
durable queue
batch client
extension proposal UI
```

The extension side panel is responsible for:

```text
Observing / Paused status

Pause / Resume

Excluded domains

Recent Mia activity

Detected suggestion cards

Yes / No / Edit interaction
```

The side panel does **not** contain backend inference logic.

---

## C2. Suggestion UX

A proposed workflow should render approximately:

```text
Mia noticed something

Log receipt emails to your expense sheet

You've done this 4 times recently.

Mia thinks the workflow is:
1. Open receipt email
2. Find receipt total
3. Open expense sheet
4. Add receipt

Confidence: 87%

[Yes] [No] [I have edits]
```

### Yes

```text
decision = "accept"
```

### No

```text
decision = "dismiss"
```

### I have edits

Allow free-text correction.

Example:

```text
Only do this for reimbursement receipts over $25.
```

Send:

```json
{
  "decision": "edit",
  "userEdits": "Only do this for reimbursement receipts over $25."
}
```

---

## C3. Web frontend

**Owner: Ryan**

Ryan owns:

```text
OAuth connection page
Google connection status
workflows page
Run button
live run status
approval UI
run result
dashboard outside the Chrome extension
```

Ryan does not own:

```text
content.js
service-worker.js
extension event collection
extension privacy controls
extension side panel
backend logic
```

---

# PART D — TEAM OWNERSHIP

## D1. Anika — Chrome extension

Owns:

```text
manifest.json
content.js
service-worker.js

side panel UI

MiaEvent construction
semantic context extraction
sanitization

pause/resume
excluded domains

durable queue
batch ingestion client

Yes / No / Edit proposal UI
```

Primary contract boundary:

```text
MiaEvent → POST /v1/events/batch
```

---

## D2. Kathy — Detection backend

Owns:

```text
POST /v1/install
install identity/token validation

event ingestion
event DB

pattern miner
LLM analyst

suggestion generation
suggestion feedback persistence

suggestions API

fallback detection dataset
DEMO_MODE
```

No UI.

---

## D3. Poshitha — Agent

Owns:

```text
agent runner
Google API tools

read_gmail()
append_to_sheet()

workflow execution
run status state machine
needs_approval behavior
```

Co-owns OAuth integration.

---

## D4. Ryan — Web frontend

Owns:

```text
OAuth connection UX

workflows web page
Run button

run progress
run result

unexpected-action approval UI

web dashboard
```

No backend logic.

---

# PART E — INTEGRATION SEAMS

There are four frozen seams.

## Seam 1 — Observation

```text
Anika
MiaEvent

        ↓

Kathy
POST /v1/events/batch
```

---

## Seam 2 — Detection

```text
Kathy
Suggestion

        ↓

Anika / Ryan
Suggestion UI
```

---

## Seam 3 — Feedback

```text
Anika
Yes / No / Edit

        ↓

Kathy
POST /v1/suggestions/:id/feedback
```

---

## Seam 4 — Execution

```text
Suggestion.workflowKey

        ↓

Ryan
Run

        ↓

Poshitha
POST /v1/workflows/:workflowKey/run
```

For v1:

```text
workflowKey = "gmail_to_sheet"
```

---

# PART F — DEMO

## F1. Target workflow

```text
Gmail → Google Sheets receipt / expense loop
```

Controlled key:

```text
gmail_to_sheet
```

Human repeatedly performs:

```text
open receipt email
    ↓
copy / identify amount
    ↓
switch to expense sheet
    ↓
append row
```

Mia detects the repeated pattern.

---

## F2. Detection moment

Mia proposes:

> **Log your receipt totals into the expenses sheet.**
>
> You've repeated this workflow several times.
>
> Mia can prepare it for you automatically when you choose to run it.

Card displays:

```text
evidence
confidence
estimated time saved

Yes
No
I have edits
```

---

## F3. Execution moment

User accepts.

Nothing happens yet.

The workflow becomes available.

User explicitly clicks:

```text
Run
```

Agent:

```text
reads receipt email
    ↓
extracts receipt amount
    ↓
appends correct row to Sheet
```

Frontend displays:

```text
✓ Reading receipt
✓ Extracting amount
✓ Opening expense tracker
✓ Adding row
✓ Complete
```

### Demo success condition (multi-workflow)

The demo shows **however many workflows are in `working` status** in the
Workflow Registry (**B7**), with the agent **selecting the right tool per
detected pattern** — not a single hardcoded path. With one working workflow the
demo is one flow; as more reach `working`, the demo grows to show the agent
choosing between them.

The approval boundary (**B5**) stays visible throughout: any unexpected
consequential action pauses with `status = "needs_approval"` and waits for the
user, regardless of which workflow is running.

Not-yet-`working` registry rows are vision-slide items only (B7 build
discipline); they are never shown as if they execute.

---

## F4. Learning / edit moment

If possible within hackathon time, demonstrate:

Mia proposes:

> Log receipt emails to the expense sheet.

User selects:

```text
I have edits
```

and writes:

> Only do this for reimbursement receipts over $25.

Backend stores this correction.

This proves that Mia does not merely detect clicks; she can begin learning the user's **rules and judgment**.

Full automatic policy induction is P1 after the end-to-end happy path works.

---

# PART G — FREEZE ORDER

Do these together before coding independently.

### 1. Freeze event contract

Confirm:

```text
MiaEvent
detail fields
semantic context
privacy rules
```

### 2. Freeze ingestion

Confirm:

```text
POST /v1/install
POST /v1/events/batch
```

### 3. Freeze suggestion contract

Confirm:

```text
Suggestion
GET /v1/suggestions
POST /v1/suggestions/:id/feedback
```

### 4. Freeze executable workflow

```text
WorkflowKey = "gmail_to_sheet"
```

Poshitha locks this workflow.

### 5. Freeze run contract

Confirm:

```text
POST /v1/workflows/:workflowKey/run
GET /v1/workflows/runs/:runId
POST /v1/workflows/runs/:runId/approve
```

### 6. Freeze ownership

```text
Anika  = extension + extension side panel
Kathy  = detection backend
Poshitha = agent
Ryan   = web frontend
```

### 7. Freeze fallback

```text
DEMO_MODE=true
```

Kathy owns fallback implementation.

---

# PART H — ACCEPTANCE TESTS

The system is done only when these pass.

## Detection / extension

### 1.
Reposting the same batch does not duplicate events.

### 2.
Queued events survive service-worker suspension/restart.

### 3.
Events remain queued while the backend is offline.

### 4.
Pausing Mia stops collection immediately.

### 5.
Excluded domains produce zero events.

### 6.
Password fields produce zero events.

### 7.
Stored URLs contain no query strings or fragments.

### 8.
Clipboard contents never appear in extension or backend storage.

### 9.
Raw form values never appear in extension or backend event storage.

### 10.
Semantic context contains labels/context only, not arbitrary page contents.

### 11.
A few repeated receipt runs produce a grounded suggestion.

### 12.
Every suggestion includes evidence from stored events.

### 13.
Dismissing and restoring a suggestion persists.

### 14.
Yes / No / Edit feedback persists.

### 15.
An edited suggestion stores the user's correction for future analysis.

---

## Execution

### 16.
Accepting a suggestion does **not** execute anything.

### 17.
An agent run begins only after the user explicitly clicks Run.

### 18.
OAuth yields a server-side token capable of reading Gmail and appending to Sheets.

### 19.
A real `gmail_to_sheet` run appends the correct row.

### 20.
The run reports live:

```text
steps[]
status
result{}
```

### 21.
An unexpected consequential action produces:

```text
status = "needs_approval"
```

and waits for the user.

### 22.
The agent resumes only after:

```text
POST /v1/workflows/runs/:runId/approve
```

### 23.
With:

```text
DEMO_MODE=true
```

the full demo runs end-to-end using prerecorded/canned data without depending on live capture or Google API availability.

---

# FINAL SYSTEM FLOW

```text
USER WORKS NORMALLY
        ↓
MIA CHROME EXTENSION
observes + sanitizes
        ↓
MiaEvent
        ↓
DURABLE LOCAL QUEUE
        ↓
/v1/events/batch
        ↓
PATTERN MINER
        ↓
LLM ANALYST
        ↓
SUGGESTION
        ↓
MIA SIDE PANEL
        ↓
 ┌─────────┬─────────┬──────────────┐
 │   YES   │   NO    │ I HAVE EDITS │
 └────┬────┴─────────┴───────┬──────┘
      │                      │
      ↓                      ↓
  ACCEPTED              FEEDBACK STORED
      │
      ↓
WORKFLOW AVAILABLE
      │
      ↓
USER CLICKS RUN
      │
      ↓
workflowKey
      │
      ↓
AGENT
      │
      ↓
GMAIL / SHEETS TOOLS
      │
      ↓
RESULT

If agent encounters an unexpected
consequential action:

      ↓
NEEDS APPROVAL
      ↓
USER APPROVES / CANCELS
```

## v1 principle

**Mia watches enough to understand the work, but collects as little of the user's actual content as possible.**

**Mia proposes; the user decides.**

**Mia never initiates an automation on her own.**
