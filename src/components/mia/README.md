# MIA personality kit

## Setup
```
npm install framer-motion
```
Drop all four files into your components folder, then import `MiaDemo` anywhere to see all 7 states with a click-through switcher — no backend, no extension, no other teammate needed.

## Files
- `mia-theme.css` — color/motion tokens
- `mia-personality.ts` — the voice rules, encoded as functions (single source of truth — pull copy from here, don't hand-write it in screens)
- `MiaAvatar.tsx` — the animated mascot, driven entirely by a `state` prop
- `MiaDemo.tsx` — standalone test harness with mock data matching the shape `/suggestions` should eventually return

## The one rule to keep in your head
Whimsy in the decoration (idle, thinking, running, success). Serious and precise in the moments that matter (confirming, failure). Never mix them — see the comment block at the top of `mia-personality.ts` for the reasoning.

## Wiring in real data later
When Kathy's `/suggestions` endpoint is ready, swap `DEMO_WORKFLOW` in `MiaDemo.tsx` for the real fetched object — as long as it has `trigger`, `action`, `source`, `target` fields (or you adjust `MiaWorkflow` to match her actual shape), everything else just works.
