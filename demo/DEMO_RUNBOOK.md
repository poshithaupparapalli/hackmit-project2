# Mia — Demo Runbook

## Before judges arrive

1. Start with a clean `backend/data/mia.db`.
2. Make sure the backend has a real `OPENAI_API_KEY`.
3. Start the backend on its normal address:
   ```bash
   cd backend
   source .venv/bin/activate
   uvicorn app.main:app --host 127.0.0.1 --port 8000
   ```
4. From the repo root, with the backend venv still active:
   ```bash
   python demo/seed_demo_week.py
   ```
5. Open the Mia dashboard and verify you have:
   - a receipt → spreadsheet suggestion,
   - an email → Calendar suggestion,
   - ideally a scheduling Rule.
6. Connect Google OAuth.
7. Create/choose the real Google Sheet used for the demo and configure:
   - `MIA_EXPENSE_SHEET_ID`
   - `MIA_EXPENSE_SHEET_RANGE` (default can be `Sheet1!A:D`)
8. For reliability, use Gmail labels:
   - `mia-demo-receipts`
   - `mia-demo-calendar`

   Configure:
   ```bash
   MIA_GMAIL_TEST_QUERY="label:mia-demo-receipts"
   MIA_CALENDAR_GMAIL_QUERY="label:mia-demo-calendar"
   ```
9. Prepare but do NOT process the two fresh live emails from the fixture files.
10. Replace the calendar fixture attendee with an email address you control.

---

# Suggested 3–4 minute demo

## Beat 1 — “Mia watched me work”

**Say:**

> “Mia is an AI apprentice. Instead of asking you to describe what should be automated, it learns by watching how you already work. For this demo, Mia has one synthetic week of an executive assistant's work history.”

Open the suggestions view.

## Beat 2 — Show that the suggestion is specific

Open the receipt suggestion.

Point to:
- trigger,
- steps,
- evidence.

**Say:**

> “It didn't just notice that Gmail and Sheets are open together. It learned the task: receipt totals from email go into this specific expense spreadsheet.”

Read one evidence line that includes the receipt subject / `Total` / `Executive Office Expenses` / `Amount`.

## Beat 3 — Accept is not execution

Click **Yes / Accept**.

**Say:**

> “This confirms that Mia understood the workflow. It still hasn't done anything.”

Show it move to Active Automations.

For the receipt workflow, set **Run automatically**.

**Say:**

> “For a routine, low-risk task like receipt logging, I can let Mia handle future instances automatically.”

## Beat 4 — Fresh receipt proves the workflow runs

Introduce/send the fresh `Receipt — Cambridge Taxi — Sep 20` email with the `mia-demo-receipts` label.

Let the watcher find it.

Show the completed run / Recent History, then open the real Google Sheet.

Expected appended row is structurally:

```text
[date from email header] | [sender/vendor] | $42.18 | Receipt — Cambridge Taxi — Sep 20
```

**Say:**

> “This email wasn't part of the history Mia learned from. It's a new instance of the workflow.”

## Beat 5 — Different autonomy for scheduling

Open the email → Calendar automation and choose **Ask me every time**.

Introduce/send the fresh Meridian Ventures email with the `mia-demo-calendar` label.

Wait for/show Mia's prompt asking whether to handle it.

**Say:**

> “The workflow is known, but for scheduling I want Mia to check with me before it starts.”

Approve the run.

## Beat 6 — Consequential action checkpoint

Mia should parse the email and then reach `needs_approval` immediately before the actual Calendar insert / invite send.

Show:

> **Send meeting invitations?**

**Say:**

> “Even after I've approved the workflow, Mia hits another checkpoint before an external action that contacts someone.”

Click Approve.

Open Google Calendar and show the created event.

## Beat 7 — Rule ≠ runnable automation

Open the scheduling Rule.

**Say:**

> “Mia also notices judgment, not just repeated clicks. Here it noticed how this assistant treats early meetings. But this is a rule, not a workflow we currently know how to enforce, so Mia doesn't pretend there's a Run button.”

If the model inferred the investor exception, point it out. If it only inferred the broader time preference, do not overclaim the exception.

## Optional Beat 8 — Chat

Ask:
> “Why did you suggest the receipt workflow?”

or:
> “What evidence did you use?”

Keep this optional. If time is tight, stop after the rule.

---

# Core story

The demo should communicate:

```text
Mia observes work
→ understands a repeated job
→ proposes it with evidence
→ the user decides whether Mia understood correctly
→ the user chooses an autonomy level
→ a brand-new instance appears
→ Mia handles it
→ consequential actions still require approval
→ Mia can also learn rules it isn't yet able to execute
```

Do not spend demo time scrolling through every suggestion or showing raw event JSON.
