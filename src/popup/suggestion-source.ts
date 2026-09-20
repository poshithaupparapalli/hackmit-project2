/**
 * The popup's only data seam.
 *
 * NOTE FOR ANIKA: nothing in the extension exposes suggestion state yet, so
 * this reads a storage key that is PROPOSED, NOT AGREED. When the service
 * worker starts writing the active suggestion, either keep this key or tell
 * Ryan the real one — this file is the single place it needs changing.
 */
import type { MiaWorkflow } from '../components/mia/mia-personality';

/** Proposed key the service worker would write the active suggestion to. */
export const ACTIVE_SUGGESTION_KEY = 'mia:activeSuggestion';

/**
 * TODO: point at the real workflows page once it exists — there is currently
 * no dashboard in this repo, so this opens the frontend dev server root.
 */
export const MIA_DASHBOARD_URL = 'http://localhost:5173/';

/**
 * Fallback so the popup renders during `npm run dev` in a normal tab, where
 * there is no extension storage. Same shape as MiaDemo's DEMO_WORKFLOW.
 */
const DEMO_SUGGESTION: MiaWorkflow = {
  trigger: '3 receipt emails from the last week',
  action: 'add a row to your Expenses sheet for each one',
  source: 'Gmail',
  target: 'Expenses sheet',
};

function hasStorage(): boolean {
  return typeof chrome !== 'undefined' && chrome?.storage?.local !== undefined;
}

/** Returns the active suggestion, or null when MIA has noticed nothing new. */
export async function readActiveSuggestion(): Promise<MiaWorkflow | null> {
  if (!hasStorage()) return DEMO_SUGGESTION;
  try {
    const stored = await chrome!.storage!.local.get(ACTIVE_SUGGESTION_KEY);
    const value = stored[ACTIVE_SUGGESTION_KEY];
    return value ? (value as MiaWorkflow) : null;
  } catch {
    return null;
  }
}

/** Dismiss clears the suggestion; it never opens the dashboard. */
export async function clearActiveSuggestion(): Promise<void> {
  if (!hasStorage()) return;
  try {
    await chrome!.storage!.local.remove(ACTIVE_SUGGESTION_KEY);
  } catch {
    /* popup is closing anyway — nothing useful to do here */
  }
}

/** Hands off to the dashboard, where approve/edit/delete/stats all live. */
export function openDashboard(): void {
  if (typeof chrome !== 'undefined' && chrome?.tabs) {
    chrome.tabs.create({ url: MIA_DASHBOARD_URL });
    return;
  }
  window.open(MIA_DASHBOARD_URL, '_blank', 'noopener');
}
