# Mia

# Inspiration

At HackMIT, a mentor told us: *“I was surprised not everyone is using agentic AI.”*

It was a reality check. Inside the tech bubble, we assume agentic workflows are second nature. But in reality, only 16% of adults use AI daily according to research. 

Every AI startup right now is selling you a blank canvas and saying, *"Go build an agentic workflow!"*

But that assumes people know how to think in workflows. The reality is that the vast majority of professionals—operations managers, accountants, administrative staff, and small business owners—don’t think like systems architects. They wake up, juggle fifteen open browser tabs, and spend hours on fragmented, manual grunt work: copying invoice totals from Gmail into QuickBooks.

These users desperately need automation, but existing tools demand that they design complex pipelines from scratch when they don’t even know what’s possible. They don't have the time to orchestrate multi-agent pipelines; they just want their busywork to disappear.

We built Mia to meet people where they actually work, replacing the intimidating blank canvas with intuitive and proactive automation.

---

# What It Does

Mia is the dream intern you never had to train. Mia listens in your browser, observes the repetitive chores in your daily workflow, and turns them into 1-click automations before you even think to ask.

```
OBSERVE ➔ UNDERSTAND ➔ PROPOSE ➔ USER CORRECTS/ACCEPTS ➔ DELEGATE ➔ LEARN FROM FEEDBACK
```

* **Observes your daily grunt work:** Runs as a lightweight browser companion that notices when you’re repeating steps—like cross-referencing tabs, copying values from web invoices, or updating spreadsheets.
* **Proactively taps you on the shoulder:** Instead of waiting for a prompt, Mia offers bite-sized suggestions directly in your browser sidebar when it spots a pattern:  
  > *"I noticed you’ve extracted receipt numbers from Gmail into your budget sheet 4 times this morning. Want me to finish the rest?"*
* **Turns habits into 1-click automations:** When you approve a suggestion, Mia generates a permanent, reusable mini-skill tailored to your exact routine—no code or workflow builder required.
* **Executes tasks safely across your apps:** Connects with work tools like Google Sheets, Calendar, and Notion to do the heavy lifting in the background, pausing for your sign-off before executing any critical action.
* **Learns your preferences over time:** Every time you accept, tweak, or dismiss a suggestion, Mia gets smarter about what to automate. Through an interactive conversational layer, you can audit its reasoning (*“Why did you suggest this?”*) or set its boundaries (*“Only do this for receipts over $25”*) so you’re always in control.

---

# How We Built It

### Tech Stack
* **Client Extension:** JavaScript, Chrome Extension Manifest V3 (`chrome.sidePanel`, `chrome.storage`, `chrome.alarms`)
* **Dashboard & Side Panel UI:** React, TypeScript, Tailwind CSS, Framer Motion
* **Pattern Detection & Ingestion:** Python, FastAPI, Pydantic, SQLite
* **Synthesis Engine:** OpenAI API (Structured Outputs / JSON mode)
* **Execution Agent:** Python, FastAPI, `google-api-python-client`, OAuth 2.0, multi-threaded task runner

### Architecture
* **Observation (Chrome Extension):** Tracks user actions (clicks, focus changes, clipboard transitions) across browser tabs. It uses a zero-content model—capturing only structural DOM paths and data types (e.g., timestamps, currency) rather than raw text or private inputs. Events are queued locally in `chrome.storage` and flushed in periodic batches.
* **Analysis Engine (FastAPI + SQLite):** Segments incoming events into sessions and uses a sliding-window miner to detect repetitive interaction loops. It formats these patterns into digests and passes them to OpenAI’s structured JSON mode to propose a workflow blueprint.
* **Agent Runner (Python Service):** An isolated worker service that executes accepted workflows asynchronously using official Google Workspace APIs.

---

# Individual Contributions

* **Poshitha:** Built the execution agent service and integrated third-party Google Workspace APIs for background task runs.
* **Kathy:** Engineered the backend detection engine, session pattern miner, and LLM workflow synthesis pipeline.
* **Anika:** Developed the React 19 side panel interface, extension integration, and state management.
* **Ryan:** Led UI/UX design and crafted the responsive frontend components with Framer Motion animations.

---

# Challenges We Ran Into

Not every web platform allows agents to take actions on a user's behalf without explicit integrations. For reliability and security, we opted against simulating artificial clicks in the browser, choosing instead to prioritize direct, authenticated connections with core power apps like Google Workspace for this demo.

---

# Accomplishments That We're Proud Of

* **Pivoting Under Pressure:** We’re incredibly proud of how our team adapted—after spending hours stuck in ideation paralysis, we made the call to pivot to Mia and managed to ship a complete, working prototype in 15 hours.
* **First-Time Hacker:** This was Anika’s very first hackathon—here's to many more to come!

---

# What We Learned

* **Context Is Everything:** Building an effective agent isn’t just about the model itself; it’s about grounding the agent in compounding, real-time operational context so suggestions feel natural rather than disruptive.
* **Self-Improving Feedback Loops:** We learned how to design better human-in-the-loop systems. By capturing user approvals, dismissals, inline edits, and recurring behavioral motifs, the agent improves its pattern recognition over time.

---

# What's Next for Mia

Moving forward, we plan to expand Mia’s integration ecosystem by adding direct integrations with key productivity apps like Notion, Slack, and Airtable. To scale Mia beyond standard APIs, we plan to integrate Browserbase for managed headless browser execution. This will enable our agent to securely and autonomously navigate web pages, fill out complex forms, and interact with dynamic sites—vastly widening the scope of workflows Mia can automate.
