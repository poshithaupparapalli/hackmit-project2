/**
 * MIA — Chrome extension toolbar popup (Manifest V3 default_popup).
 *
 * Layout, spacing and type follow the Figma Make design's `Popup` component:
 * a gradient hero (wordmark + status + one-line teaser) over a white content
 * area holding the suggestion and its two actions. The design deliberately
 * carries no mascot here — MiaAvatar appears on the dashboard, not the popup.
 *
 * Deliberately NOT a second dashboard. Approve, edit, delete, history and
 * stats all live on the dashboard — do not add them here.
 *
 * All copy comes from mia-personality.ts and all color from mia-theme.css
 * tokens; this file forks neither.
 */
import { useEffect, useMemo, useState } from 'react';
import {
  idleLine,
  noticedLine,
  suggestingLine,
  type MiaWorkflow,
} from '../components/mia/mia-personality';
import { clearActiveSuggestion, openDashboard, readActiveSuggestion } from './suggestion-source';
import '../components/mia/mia-theme.css';
import './popup.css';

export function PopupApp() {
  const [suggestion, setSuggestion] = useState<MiaWorkflow | null>(null);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    let active = true;
    readActiveSuggestion().then((next) => {
      if (!active) return;
      setSuggestion(next);
      setLoaded(true);
    });
    return () => {
      active = false;
    };
  }, []);

  // Held in state so the randomized idle copy stays put for the life of the
  // popup — re-rolling it on every render would read as a glitch.
  const line = useMemo(
    () => (suggestion ? suggestingLine(suggestion) : idleLine()),
    [suggestion],
  );

  async function handleDismiss() {
    await clearActiveSuggestion();
    setSuggestion(null);
    // Dismiss closes the popup outright and opens nothing. In a normal browser
    // tab (npm run dev) close() is a no-op, so the cleared idle state above is
    // what you see there instead.
    window.close();
  }

  return (
    <div className="mia-popup">
      <div className="mia-popup__hero">
        <div className="mia-popup__bar">
          <span className="mia-popup__wordmark">mia</span>
          <span className="mia-popup__status">{loaded && suggestion ? 'New' : 'Observing'}</span>
        </div>

        <div className="mia-popup__hero-body">
          {loaded && (
            <p className="mia-popup__hero-line">{suggestion ? noticedLine() : line}</p>
          )}
        </div>
      </div>

      <div className="mia-popup__content">
        {loaded &&
          (suggestion ? (
            <div className="mia-popup__fade-up">
              <p className="mia-popup__line">{line}</p>
              <div className="mia-popup__actions">
                <button className="mia-popup__primary" onClick={openDashboard}>
                  Open MIA
                </button>
                <button className="mia-popup__dismiss" onClick={handleDismiss}>
                  Dismiss
                </button>
              </div>
            </div>
          ) : (
            <div className="mia-popup__idle-actions">
              <button className="mia-popup__link" onClick={openDashboard}>
                Open MIA →
              </button>
            </div>
          ))}
      </div>
    </div>
  );
}
