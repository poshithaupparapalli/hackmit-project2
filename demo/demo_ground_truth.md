# Mia Demo Ground Truth

## Persona
**Maya Patel**, Executive Assistant to **Jordan Lee**, CEO of **Northstar**.

Synthetic history covers **September 14–18, 2026** and contains **88 canonical MiaEvents**.

## Intended learned workflow 1 — Receipts → expense spreadsheet

Five separate work sessions show the same structure:

- `Receipt from Uber — Sep 14`
- `Delta receipt — BOS to JFK`
- `Marriott receipt — Cambridge`
- `Staples receipt — Office supplies`
- `Amtrak receipt — Northeast Regional`

In each session Maya:
1. opens the receipt in Gmail,
2. interacts with a field labeled `Total`,
3. copies a value classified as `currency`,
4. moves to `Executive Office Expenses`,
5. pastes/edits the `Amount` field.

### Desired suggestion
Something semantically close to:

> **Log receipt totals from email into the Executive Office Expenses spreadsheet.**

The exact wording is LLM-generated and may differ.

For the suggestion to become executable as `gmail_to_sheet`, the generated suggestion text must naturally include:
- at least one of: `gmail`, `mail.google`, `receipt`, `email`
- and at least one of: `sheet`, `spreadsheet`, `docs.google`

## Intended learned workflow 2 — Meeting email → Calendar

Five separate sessions show meeting-request emails followed by creation of Calendar events.

### Desired suggestion
Something semantically close to:

> **Turn meeting-request emails into Google Calendar events.**

For it to become executable as `email_to_calendar`, generated suggestion text must include:
- at least one of: `gmail`, `mail.google`, `email`, `meeting`, `invite`, `invitation`
- and at least one of: `calendar`, `event`, `schedule`

**Important:** this requires the real LLM path. The backend heuristic fallback cannot generate `email_to_calendar`.

## Intended learned rule

Routine external requests before 10 AM are moved later:
- Acme Ventures: requested 8:30 AM → selected 10:30 AM
- Northstar Legal: requested 9:00 AM → selected 11:00 AM
- Q4 planning: requested 9:30 AM → selected 10:30 AM

Control examples:
- Meridian Partners requested 2:00 PM → remains 2:00 PM
- Horizon Capital is explicitly an **Investor meeting** requested for 8:00 AM → remains 8:00 AM

### Desired rule
Ideally something close to:

> **Schedule routine external meetings at or after 10 AM, except investor meetings.**

Rule generation is intentionally LLM-driven and therefore not guaranteed to use that exact wording. A `rule` should have no runnable `workflowKey`.

## Noise / negative examples

The dataset also contains one-off visits to:
- Notion weekly priorities
- a Google Doc for board prep
- Google Drive
- LinkedIn
- Kayak
- executive team notes

These are there so the history does not look like a perfectly manufactured sequence and should not create strong repeated-workflow evidence.
