# Mia

The Chrome extension is in [`extension/`](extension/). See its [setup and demo guide](extension/README.md) to load it unpacked, rehearse the receipt workflow, and connect Kathy's backend. The extension's own UI is its side panel (`extension/sidepanel.html`) — there is no separate toolbar popup.

The dashboard (`npm run dev`, then open http://localhost:5173/) is the "workflows app": connect Google, turn suggestions into active automations, run them, and see run history. It expects two local processes:

- Kathy's detection backend on `http://localhost:8000` (`cd backend && uvicorn app.main:app`) — suggestions.
- Poshitha's agent on `http://localhost:8010` (from the repo root: `uvicorn agent.server:app --port 8010`) — execution + the Google OAuth "Connect" button.

Override either with `VITE_MIA_BACKEND_URL` / `VITE_MIA_AGENT_URL`.

[`MIA_CONTRACTS.md`](MIA_CONTRACTS.md) is the frozen v1.1 integration contract. Backend detection, OAuth, workflow execution, and the web frontend are owned separately.
