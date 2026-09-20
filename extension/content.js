(() => {
  const P = MiaPrivacy, S = MiaSemantics;
  // Fail closed until the worker supplies settings. Only the worker can access
  // local storage, including installation credentials.
  let settings = null, blocked = true;
  let editTimers = new Map(), editLengths = new WeakMap();
  const formMethods = new WeakMap();
  let scrollMilestones = new Set(), scrollScheduled = false;
  function active() {
    return settings && !settings.paused && !blocked && !P.isExcludedDomain(location.hostname, settings.excludedDomains);
  }
  function applySettings(message) {
    settings = message.settings; blocked = Boolean(message.blocked);
    for (const timer of editTimers.values()) clearTimeout(timer);
    editTimers.clear(); editLengths = new WeakMap();
  }
  function send(type, detail, target) {
    if (!active() || S.isPassword(target) || S.isPassword(document.activeElement)) return;
    const observation = P.sanitizeObservation({ type, detail, context: S.extractSemanticContext(target) });
    if (!observation) return;
    // chrome.runtime throws synchronously (not just a rejected promise) once
    // the extension has been reloaded/updated out from under an already-open
    // tab's content script ("Extension context invalidated"). Fail closed —
    // the tab picks back up cleanly on its next reload — instead of an
    // uncaught error on every subsequent click/edit/scroll in this tab.
    try {
      chrome.runtime.sendMessage({ kind: 'observe', observation }).catch(() => { settings = null; });
    } catch {
      settings = null;
    }
  }
  try {
    chrome.runtime.onMessage.addListener(message => {
      if (message.kind === 'settings') applySettings(message);
      if (message.kind === 'navigation') { scrollMilestones = new Set(); }
    });
    chrome.runtime.sendMessage({ kind: 'settings:get' }).then(response => {
      if (response?.ok) applySettings(response.data);
    }).catch(() => {});
  } catch {
    // Context was already invalidated before this script finished setting up.
  }

  document.addEventListener('click', event => {
    if (!active() || !event.isTrusted || S.isPassword(event.target)) return;
    const target = S.actionTarget(event.target);
    if (!target) return;
    if (target.form && (target.matches('button') && target.type === 'submit' || target.matches('input[type="submit"], input[type="image"]'))) formMethods.set(target.form, { via: 'button', at: Date.now() });
    send('click', { tag: target.tagName.toUpperCase(), role: target.getAttribute('role') || (target.matches('button') ? 'button' : target.matches('a') ? 'link' : ''), label: S.labelFrom(target), ...S.urlDetail(target.closest('a')?.href, 'href') }, target);
  }, true);

  function recordEdit(target) {
    clearTimeout(editTimers.get(target)); editTimers.delete(target);
    if (!active() || S.isPassword(target) || !target.isConnected) return;
    // Character counts only. Never retain values in closures, messages or storage.
    // Select/checkbox/radio length is omitted because string length would not
    // describe the interaction and option text is private.
    let length;
    if (target.matches('input:not([type="checkbox"]):not([type="radio"]):not([type="file"]), textarea')) length = target.value.length;
    else if (target.isContentEditable) length = target.textContent.length;
    const signature = length === undefined ? null : length;
    if (signature !== null && editLengths.get(target) === signature) return;
    editLengths.set(target, signature);
    send('edit', { tag: target.tagName, inputType: target.isContentEditable ? 'contenteditable' : target.matches('select') ? 'select' : target.matches('textarea') ? 'textarea' : target.type, name: S.labelFrom(target), ...(length !== undefined ? { length } : {}) }, target);
  }
  document.addEventListener('input', event => {
    if (!active() || !event.isTrusted) return;
    const target = S.editable(event.target);
    if (!target || S.isPassword(target)) return;
    editLengths.delete(target); // Same-length replacements are still edits.
    clearTimeout(editTimers.get(target));
    editTimers.set(target, setTimeout(() => recordEdit(target), 800));
  }, true);
  for (const type of ['change', 'focusout']) document.addEventListener(type, event => {
    if (!active() || !event.isTrusted) return;
    const target = S.editable(event.target);
    if (target && !S.isPassword(target) && (type === 'change' || editTimers.has(target))) recordEdit(target);
  }, true);

  document.addEventListener('submit', event => {
    if (!active() || !event.isTrusted || S.isPassword(document.activeElement)) return;
    const form = event.target;
    const method = formMethods.get(form);
    formMethods.delete(form);
    send('submit', { name: S.labelFrom(form), ...S.urlDetail(form.action, 'action'), fieldCount: form.elements?.length || 0, via: method && Date.now() - method.at < 2000 ? method.via : event.submitter ? 'button' : 'unknown' }, form);
  }, true);

  document.addEventListener('copy', event => {
    if (!active() || !event.isTrusted || S.isPassword(event.target) || S.isPassword(document.activeElement)) return;
    // Do not access clipboardData or materialize selected text. Count a simple
    // selection via offsets; complex selections omit unavailable metadata.
    const target = S.elementOf(event.target);
    let length, source = target;
    if (target?.matches('input, textarea') && Number.isInteger(target.selectionStart)) length = target.selectionEnd - target.selectionStart;
    else {
      const selection = document.getSelection();
      if (selection?.rangeCount) {
        source = S.elementOf(selection.anchorNode) || target;
        const range = selection.getRangeAt(0);
        if (range.startContainer === range.endContainer && range.startContainer.nodeType === 3) length = Math.abs(range.endOffset - range.startOffset);
      }
    }
    send('copy', length === undefined ? {} : { length }, source);
  }, true);
  document.addEventListener('paste', event => {
    if (!active() || !event.isTrusted || S.isPassword(event.target)) return;
    const target = S.actionTarget(event.target);
    // Paste length cannot be measured without reading clipboard text. Omit it.
    send('paste', { targetTag: target?.tagName, targetName: S.labelFrom(target) }, target);
  }, true);
  document.addEventListener('keydown', event => {
    if (!active() || !event.isTrusted || S.isPassword(event.target)) return;
    const target = S.elementOf(event.target);
    if (event.key === 'Enter' && target?.form && !target.matches('textarea')) formMethods.set(target.form, { via: 'enter', at: Date.now() });
    if (!(event.ctrlKey || event.metaKey) || event.altKey || event.repeat) return;
    const key = ({ c: 'Copy', v: 'Paste', x: 'Cut', a: 'Select all', z: event.shiftKey ? 'Redo' : 'Undo', y: 'Redo', f: 'Find', s: 'Save' })[event.key.toLowerCase()];
    // An allowlist of command names, never an arbitrary key or typed character.
    if (key) send('shortcut', { key }, target);
  }, true);
  document.addEventListener('visibilitychange', () => send('focus', { visible: !document.hidden }, null));
  window.addEventListener('focus', () => send('focus', { visible: !document.hidden }, null));
  document.addEventListener('scroll', () => {
    if (!active() || scrollScheduled) return;
    scrollScheduled = true;
    requestAnimationFrame(() => {
      scrollScheduled = false;
      if (!active()) return;
      const root = document.scrollingElement;
      const extent = root.scrollHeight - root.clientHeight;
      if (extent <= 0) return;
      const depth = Math.min(100, Math.round(root.scrollTop / extent * 100));
      for (const milestone of [25, 50, 75, 100]) if (depth >= milestone && !scrollMilestones.has(milestone)) {
        scrollMilestones.add(milestone); send('scroll', { depth: milestone }, null);
      }
    });
  }, { passive: true });
})();
