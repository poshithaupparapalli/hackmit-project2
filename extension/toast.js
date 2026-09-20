/**
 * MIA in-page toast.
 *
 * A floating card the content script injects onto the page when MIA notices a
 * repetitive workflow. Not a modal: it never blocks the page, never traps
 * focus, and never covers the page's own chrome.
 *
 * Rendered inside a closed-ish Shadow DOM so the host page's CSS cannot reach
 * in and ours cannot leak out — this runs on every http(s) page, so isolation
 * is not optional.
 *
 * Visual spec: the finished Figma Make design (MIA-Chrome-Extension-Design).
 * Wordmark only — this card carries no avatar/mascot by design.
 */
(() => {
  // content_scripts runs with all_frames:true; the toast belongs to the top
  // document only, or an ad iframe would get its own copy.
  if (window.top !== window) return;

  const HOST_ID = 'mia-toast-host';

  /**
   * Design tokens, inlined.
   *
   * A Shadow DOM stylesheet cannot reach mia-theme.css without declaring it a
   * web-accessible resource, which would expose it to every page. These values
   * mirror src/components/mia/mia-theme.css — keep them in sync.
   */
  const STYLES = `
    :host {
      all: initial;
      --mia-ink: #13102a;
      --mia-ink-soft: #7a6898;
      --mia-ink-faint: #b0a4cc;
      --mia-paper-raised: #ffffff;
      --mia-grad-1: rgba(206, 186, 240, 0.55);
      --mia-grad-2: rgba(190, 164, 232, 0.38);
      --mia-grad-mid: #f3ebfb;
      --mia-action: #1a1630;
      --mia-action-fg: #ffffff;
      --mia-font-display: 'Fraunces', Georgia, 'Iowan Old Style', serif;
      --mia-font-body: 'Inter', system-ui, -apple-system, 'Segoe UI', sans-serif;
    }

    * { box-sizing: border-box; margin: 0; padding: 0; }

    .card {
      /* Shadow DOM does not stop INHERITED properties. A page-wide
         "* { text-transform: uppercase !important }" matches our host element
         and inherits straight in, so reset everything here and re-declare.
         The all property never touches custom properties, so --mia-* still
         resolve. (No backticks in here: this is inside a template literal.) */
      all: initial;
      display: block;
      box-sizing: border-box;
      position: fixed;
      right: 20px;
      bottom: 20px;
      z-index: 2147483647;
      width: 360px;
      max-width: calc(100vw - 40px);
      overflow: hidden;
      border-radius: 22px;
      background: var(--mia-paper-raised);
      font-family: var(--mia-font-body);
      color: var(--mia-ink);
      text-align: left;
      box-shadow:
        0 2px 8px rgb(80 60 160 / 0.08),
        0 8px 48px rgb(80 60 160 / 0.18);
      /* Base state is visible: if the animation never runs, the card still
         shows rather than sitting invisible at opacity 0. */
      opacity: 1;
      animation: mia-in 0.32s cubic-bezier(0.22, 1, 0.36, 1);
    }

    @keyframes mia-in {
      from { opacity: 0; transform: translateY(10px) scale(0.98); }
      to   { opacity: 1; transform: translateY(0) scale(1); }
    }

    @media (prefers-reduced-motion: reduce) {
      .card { animation: none; }
    }

    /* ── top: lilac gradient ─────────────────────────────────────────── */

    .hero {
      min-height: 200px;
      padding: 32px 28px 36px;
      background:
        radial-gradient(ellipse 70% 60% at 22% 18%, var(--mia-grad-1) 0%, transparent 55%),
        radial-gradient(ellipse 60% 70% at 82% 78%, var(--mia-grad-2) 0%, transparent 55%),
        linear-gradient(150deg, #ffffff 0%, var(--mia-grad-mid) 55%, #ffffff 100%);
    }

    .bar {
      display: flex;
      align-items: center;
      justify-content: space-between;
      margin-bottom: 28px;
    }

    .wordmark {
      font-family: var(--mia-font-display);
      font-size: 22px;
      font-weight: 900;
      letter-spacing: -0.01em;
      line-height: 1;
      color: var(--mia-ink);
    }

    .flag {
      font-size: 11px;
      font-weight: 500;
      letter-spacing: 0.1em;
      text-transform: uppercase;
      color: var(--mia-ink-faint);
    }

    .teaser {
      padding-top: 8px;
      font-size: 15px;
      line-height: 1.5;
      text-align: center;
      color: var(--mia-ink-soft);
    }

    /* ── bottom: white ───────────────────────────────────────────────── */

    .body { padding: 24px 24px 28px; }

    .line {
      margin-bottom: 20px;
      font-size: 14.5px;
      line-height: 1.65;
      color: var(--mia-ink);
    }

    .primary {
      display: block;
      width: 100%;
      padding: 9px 22px;
      border: none;
      border-radius: 999px;
      background: var(--mia-action);
      color: var(--mia-action-fg);
      font-family: var(--mia-font-body);
      font-size: 14px;
      font-weight: 600;
      cursor: pointer;
      transition: opacity 0.15s;
    }

    .primary:hover { opacity: 0.82; }
    .primary:active { opacity: 0.7; }

    .dismiss {
      display: block;
      width: 100%;
      margin-top: 10px;
      padding: 4px 0;
      border: none;
      background: none;
      color: var(--mia-ink-soft);
      font-family: var(--mia-font-body);
      font-size: 12.5px;
      text-align: center;
      cursor: pointer;
      transition: opacity 0.15s;
    }

    .dismiss:hover { opacity: 0.6; }

    .primary:focus-visible,
    .dismiss:focus-visible {
      outline: 2px solid var(--mia-action);
      outline-offset: 3px;
    }
  `;

  /**
   * These read as sentence fragments inside a larger sentence, so a trailing
   * full stop would render "...for each one.?". The backend currently returns
   * `action` as a complete capitalised sentence; strip the terminator rather
   * than print the double punctuation. Capitalisation is left alone on
   * purpose — lowercasing blindly would wreck "Gmail" or "Expense Tracker".
   */
  function clean(value) {
    return String(value || '').trim().replace(/[.!?]+$/, '').trim();
  }

  /**
   * Mirrors suggestingLine() in src/components/mia/mia-personality.ts, which
   * the extension cannot import (no bundler). Keep in sync.
   *
   * Falls back when `trigger` is absent — the backend currently returns an
   * empty trigger in demo mode, and "I noticed . Want me to…" would be worse
   * than saying nothing specific.
   */
  function suggestionText(suggestion) {
    const trigger = clean(suggestion.trigger);
    const action = clean(suggestion.action);
    if (trigger && action) return `I noticed ${trigger}. Want me to ${action}?`;
    if (action) return `I noticed a pattern you repeat. Want me to ${action}?`;
    return suggestion.summary || suggestion.title || 'I noticed a pattern you repeat.';
  }

  /** Mirrors noticedLine(). */
  const TEASER = 'I noticed something.';

  function hide() {
    document.getElementById(HOST_ID)?.remove();
  }

  function show(suggestion = {}) {
    hide(); // never stack two toasts

    const host = document.createElement('div');
    host.id = HOST_ID;
    // The page's own CSS can match this element; keep it rendering.
    host.style.setProperty('display', 'block', 'important');
    host.style.setProperty('visibility', 'visible', 'important');
    const root = host.attachShadow({ mode: 'open' });

    const style = document.createElement('style');
    style.textContent = STYLES;

    const card = document.createElement('div');
    card.className = 'card';
    card.setAttribute('role', 'status');
    card.setAttribute('aria-live', 'polite');

    const hero = document.createElement('div');
    hero.className = 'hero';
    const bar = document.createElement('div');
    bar.className = 'bar';
    const wordmark = document.createElement('span');
    wordmark.className = 'wordmark';
    wordmark.textContent = 'mia';
    const flag = document.createElement('span');
    flag.className = 'flag';
    flag.textContent = 'New';
    bar.append(wordmark, flag);
    const teaser = document.createElement('p');
    teaser.className = 'teaser';
    teaser.textContent = TEASER;
    hero.append(bar, teaser);

    const body = document.createElement('div');
    body.className = 'body';
    const line = document.createElement('p');
    line.className = 'line';
    line.textContent = suggestionText(suggestion);

    const open = document.createElement('button');
    open.className = 'primary';
    open.type = 'button';
    open.textContent = 'Open MIA';
    open.addEventListener('click', () => {
      // A content script cannot call chrome.sidePanel.open() itself — only the
      // service worker can, and only while a user gesture is in flight.
      chrome.runtime.sendMessage({ kind: 'sidepanel:open' }).catch(() => {});
      hide();
    });

    const dismiss = document.createElement('button');
    dismiss.className = 'dismiss';
    dismiss.type = 'button';
    dismiss.textContent = 'Dismiss';
    dismiss.addEventListener('click', hide);

    body.append(line, open, dismiss);
    card.append(hero, body);
    root.append(style, card);
    (document.body || document.documentElement).append(host);
  }

  chrome.runtime.onMessage.addListener(message => {
    if (message?.kind === 'toast:show') show(message.suggestion || {});
    if (message?.kind === 'toast:hide') hide();
  });

  // Exposed on the isolated-world global so it can be driven from the "Mia"
  // context in DevTools: MiaToast.show({ trigger: '…', action: '…' })
  globalThis.MiaToast = { show, hide };
})();
