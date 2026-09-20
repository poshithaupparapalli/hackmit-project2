# Mia Chrome extension

Anika's observation and proposal UI, implementing [`MIA_CONTRACTS.md` v1.1](../MIA_CONTRACTS.md). Vanilla JavaScript; no build step, backend, OAuth, Google API logic, or workflow execution code.

## Load and reload

1. Open `chrome://extensions` in Chrome 120 or newer.
2. Enable **Developer mode**, choose **Load unpacked**, and select this `extension/` directory.
3. Pin Mia in the toolbar, then click its icon to open the side panel.
4. Refresh the ordinary HTTP/HTTPS pages you want to observe. Existing tabs need a refresh after installation or extension reload.

After JavaScript, manifest, or configuration changes: click Mia's reload icon in `chrome://extensions`, refresh observed pages, and reopen the panel. Panel-only HTML/CSS changes need the panel reopened/refreshed. Chrome internal pages, the Web Store, file URLs, and Incognito are not observed. No Incognito support is declared.

## Mock versus real backend

Edit `config.js`:

```js
mock: false,                        // true only for local extension mocks
backendBaseUrl: 'http://localhost:8000',
debug: true,
```

The extension now defaults to the **real local backend** at `http://localhost:8000`. Start it from the repository root:

```sh
cd backend
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Dependencies are installed in `backend/.venv`. On a fresh checkout, follow `backend/README.md` to create that environment. Check `http://localhost:8000/health`, reload Mia in `chrome://extensions`, refresh observed tabs, and reopen the panel. After a few interactions, use **Development diagnostics → Try syncing now**; the queue should clear and **Last sync** should update. Once an event batch is acknowledged, Mia requests `/v1/analyze` automatically (at most once per minute), and the panel refreshes proposals. No OpenAI key is required for ingestion. General LLM analysis requires `OPENAI_API_KEY` in `backend/.env`; without it the current backend's heuristic fallback recognizes only the Gmail/Sheets receipt pattern. Normal mode does not seed a canned suggestion, so an initially empty proposal list is expected. The backend's periodic analyzer is also gated on 25 new events and 30 minutes since the last analysis. For an immediate analysis attempt outside Mia, run `curl -X POST http://localhost:8000/v1/analyze`, then refresh proposals.

Switch `mock: true` only when you want an isolated extension demo. Mock mode acknowledges batches locally, shows a clearly marked sample receipt suggestion, and persists Yes/No/Edit feedback locally. It does not infer anything or contact a backend. Accepted mock batches leave the unsent queue; the last 40 sanitized actions remain visible. Mode/backend-specific storage prevents mock events and credentials from being sent to a real backend. Changing mode starts/reuses that mode's separate identity/settings/history. It never silently falls back from live to mock.

Use HTTPS for a remote backend (HTTP is allowed only for localhost/loopback). HTTP/HTTPS host permissions already cover observation and backend fetches; `storage`, `alarms`, `sidePanel`, and `webNavigation` are the only explicit permissions. Host permission supplies tab URL access without requesting `tabs`. Content scripts have no direct storage access. Install tokens are used only by the worker's backend client and are never included in panel/content messages.

### What Anika needs from Kathy

- Reachable base URL for `POST /v1/install`, `POST /v1/events/batch`, `GET /v1/suggestions`, `POST /v1/suggestions/:id/feedback`, and `PATCH /v1/suggestions/:id`.
- `/v1/install` returns `{installId, installToken}`; batch ingestion validates `Authorization: Bearer <installToken>` and returns `{accepted, rejected, serverTime}`. Idempotency must be keyed by `installId + event.id`.
- Confirm installation-token authentication also applies to suggestions/feedback/PATCH (assumed here; not specified by A14), and whether GET returns an array or `{suggestions: [...]}` (both accepted).
- Confirm omitted copy `wordCount` and paste `length` are accepted. They cannot be derived without reading selected/clipboard text; privacy rules take precedence. Copy `length` is sent only when it can be counted with selection offsets. No fake zero counts are sent.
- Confirm an empty successful feedback/PATCH response (204/empty 200) or JSON response; both work.
- Real grounded receipt suggestions and backend feedback persistence; sample mock evidence does not prove mining. Kathy owns prerecorded dataset/`DEMO_MODE`, which is separate from this extension's mocks.

No real secret needs to be pasted into source. Set URL and `mock: false`, reload Mia, and refresh demo tabs.

Current repository backend compatibility: port 8000 and all five routes match; GET returns an array; suggestions/feedback/PATCH currently require no authentication (the extension's extra Bearer header is accepted); missing clipboard count fields are accepted; feedback returns `{ok: true}`. The editor is limited to the backend's 2,000-character maximum.

## Rehearse safely in five minutes

Run from the repo root:

```sh
python3 -m http.server 8765 --directory extension/fixtures
```

1. Open `http://localhost:8765/receipt.html`, with Mia's panel open and **Observing** visible.
2. Click **Open receipt**, select the synthetic `$42.18` total and copy it using your keyboard. Follow the link to the expense tracker on `127.0.0.1` (a second host).
3. Paste into **Total**, type a note, edit the editable row, and click **Add row**. Expect Receipt/Total → copy → navigation/focus → expense/paste/edit/submit.
4. Open **Development diagnostics → Recent sanitized events**. Confirm `$42.18`, typed notes, `SECRET_*`, query strings and fragments never appear. Labels such as `receipt`, `total`, and `expense` should appear. Both queue and recent history contain only sanitized events.
5. Click/type/copy/paste in the password field: those actions must produce no events. A page's earlier navigation is a separate event.
6. Pause, interact again, and confirm the feed does not grow. Resume. Exclude `127.0.0.1` while the expense tab stays open; interactions and closing that tab must produce no events. Remove it to resume collection.
7. Once a backend proposal appears, use **I have edits** and enter a correction, then **No → Restore → Yes**. Feedback success appears only after successful persistence. Acceptance does not execute anything. For an immediate canned proposal during this fixture rehearsal, explicitly enable extension mock mode; the normal backend's receipt fallback requires actual Gmail/Sheets hosts, not these localhost fixtures.

Repeat the receipt loop on Gmail and Sheets using synthetic demo data. Google's canvas editors and changing DOM may expose fewer semantic labels than the fixtures; this needs a live rehearsal. No email body, spreadsheet cell text, or arbitrary page paragraphs are traversed for context.

## Queue and restart checks

- Normal flush uses a 30-second Chrome alarm; 100 queued events trigger an immediate attempt, with a 250-event maximum batch.
- Failed requests retain events. Exponential retry starts at 30 seconds and caps at 30 minutes; retry timestamps persist. Manual sync respects retry timing.
- Accepted IDs are intersected with the submitted batch before removal. New events arriving during a request cannot be removed by that acknowledgement. Rejected IDs remain queued; free-text server rejection reasons are replaced by a generic local reason to avoid echoing private data.
- Queue caps: 5,000 events / 5 MB (5,000,000 serialized UTF-8 bytes), whichever first. New arrivals are refused when full, with a visible overflow counter; existing unsent events are preserved. This is an explicit policy for a contract gap. Offline-first events are staged without a fabricated install ID, then finalized with the real identity before ingestion. Staging reserves byte space for the identity and shares the same limits.
- Sessions renew after 15 minutes of inactivity; sequence, IDs, session and queue survive worker restarts.
- Pausing/excluding stops new events. Already collected events still sync. These controls are not deletion controls.

To test actual suspension, use live mode with an unavailable backend, create a few events, note their IDs and queue count, close worker DevTools (it can keep the worker alive), then stop the worker in `chrome://serviceworker-internals` or wait for suspension. Wake Mia via the panel and check those IDs remain. Reload the extension and refresh the page; the queue should remain. Restore the API and wait for retry: only acknowledged events should disappear. Backend idempotency must be tested with Kathy by sending the same batch twice.

## Debugging and automated checks

In `chrome://extensions`, locate Mia and click **service worker** next to **Inspect views**. Inspect storage under DevTools **Application → Extension storage → Local**. The panel includes queue count, last sync, retry time, rejected count and safe backend errors. Do not copy or log the stored identity/token. The `mia:mock:v1` storage key is the default mock state.

With Node 20+ installed:

```sh
cd extension
npm test
npm run check
node tests/live-backend.mjs
```

The live-backend check starts the actual FastAPI application on a temporary port/database and tests the extension's actual API client: installation, ingestion, accepted-ID removal, retry deduplication, suggestions, restore, and persisted feedback. It requires `backend/.venv` and never changes the running demo database. The test uses backend demo seeding only in that temporary database to exercise suggestion feedback.

`tests/browser.mjs` is an optional Playwright smoke test against real headless Chrome in a disposable profile. Set `MIA_PLAYWRIGHT_PATH` to an installed Playwright module directory and optionally `MIA_CHROME_PATH` to Chrome, then run `node tests/browser.mjs`. It starts a fixture server on port 8765 and exercises MV3 startup, real page listeners, privacy, controls, mock feedback, and persisted identity/history across a browser restart. The test uses Chrome's unpacked-extension debugging API; this is test-only, never extension code.

Validated locally: 12 automated core/API tests; manifest references and JavaScript syntax; real Chrome smoke including the receipt workflow, privacy gates, feedback and restart persistence; panel layout at 380px. Unsent queue retention across a stopped worker with a real unavailable backend remains a manual integration check (the durable queue logic is covered by the automated tests).

## Files and boundaries

- `content.js`: trusted user-event listeners, debounced edit metadata, scroll milestones and focus.
- `lib/privacy.js`, `lib/semantics.js`: allowlisted detail fields, bounded semantic context, URL/domain helpers. Context may retain page/document titles, active item titles, sheet tabs, headings, labels, short nearby structural text and semantic value categories. Secret-like strings, passwords, raw values, clipboard contents and broad page text are rejected; no blanket page scraping occurs.
- `service-worker.js`: Chrome listeners, sender validation, settings propagation, canonical event coordination and alarms.
- `lib/core.js`: serialized durable state transitions, canonical metadata, sessions, batching, backoff and accepted-ID removal.
- `lib/backend.js`: exact contract HTTP seam and isolated mocks.
- `sidepanel.*`: status, suggestions/rules, feedback, activity, exclusions and diagnostics. Backend text is rendered using `textContent`, never HTML.

## Known limits and contract clarifications

The frozen contract wins over older `context.md` endpoint/popup notes. No contract field or endpoint was renamed.

- A3 lists clipboard counts while A5 forbids clipboard reads; unavailable counts are omitted, as A2 permits a sparse `detail` record. Select/checkbox/radio edits similarly omit meaningless character counts.
- Semantic extraction is bounded and may still be vague on Gmail/Sheets because their canvas and iframe DOMs vary. Page titles and active item titles are now preserved when visible. Paths follow the contract exactly (pathname, max 500); opaque IDs in paths are retained. Query strings and fragments are always stripped.
- Context extends the existing event object without changing `schemaVersion`: `pageTitle`/`itemTitle` (200 chars each), `sectionLabel`/`formLabel`/`targetLabel` (120 each), `nearbyText` (200), and `semanticType` (32). Context is stored as JSON by the backend and appears in its semantic digest and LLM trace.
- Hash-only navigation produces sanitized `nav` events but cannot retain route text. Major scroll milestones cover the document, not every nested scrolling container. Closed shadow roots/canvas and browser-protected frames have limited visibility.
- A new blank/restricted tab has no valid website, so it emits no `tabopen`; navigating to an HTTP/HTTPS site emits `nav`. No invented host is stored.
- No endpoint for identity revocation/recovery is defined; a rejected token surfaces a backend error and keeps the queue. Repeatedly rejected batches remain queued and can eventually fill the queue; resolving the backend rejection is necessary.
- Repeated receipt detection, true suggestion evidence, server-side feedback durability and batch deduplication depend on Kathy's backend. Actual Chrome toolbar side-panel opening and live Gmail/Sheets labels should be checked before the demo.

Chrome API references: [storage access controls](https://developer.chrome.com/docs/extensions/reference/api/storage), [alarms](https://developer.chrome.com/docs/extensions/reference/api/alarms), [side panel](https://developer.chrome.com/docs/extensions/reference/api/sidePanel).
