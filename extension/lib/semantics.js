(() => {
  const { sanitizeContextText, sanitizeUrl } = MiaPrivacy;
  const editableSelector = 'input, textarea, select, [contenteditable]:not([contenteditable="false"])';
  const contextLimit = MiaPrivacy.CONTEXT_LIMITS;

  function elementOf(target) { return target?.nodeType === 1 ? target : target?.parentElement; }
  function isVisible(el) {
    if (!el || el.nodeType !== 1 || el.getAttribute("aria-hidden") === "true") return false;
    const style = el.ownerDocument?.defaultView?.getComputedStyle(el);
    return !style || (style.display !== "none" && style.visibility !== "hidden");
  }
  function isPassword(target) {
    const el = elementOf(target);
    return el?.matches('input[type="password"]') || el?.closest('input[type="password"]') != null || el?.closest('label')?.control?.type === 'password';
  }
  function editable(target) { return elementOf(target)?.closest(editableSelector); }

  function directText(el, max = 200) {
    if (!el || !isVisible(el) || editable(el)) return "";
    let text = "";
    for (const node of el.childNodes || []) {
      if (node.nodeType === 3) text += ` ${node.textContent}`;
      else if (node.nodeType === 1 && node.childElementCount === 0 && !editable(node)) text += ` ${node.textContent}`;
      if (text.length > max * 2) break;
    }
    return sanitizeContextText(text, max);
  }

  function textFrom(el, max) {
    if (!el || !isVisible(el) || editable(el)) return "";
    return sanitizeContextText(el.textContent || "", max);
  }

  function firstVisibleText(root, selectors, max) {
    for (const selector of selectors) {
      for (const el of Array.from(root.querySelectorAll(selector)).slice(0, 5)) {
        const text = directText(el, max) || textFrom(el, max);
        if (text) return text;
      }
    }
    return "";
  }

  function actionTarget(target) {
    const el = elementOf(target);
    return el?.closest('button, a, input, textarea, select, [role], label, [contenteditable]') || el;
  }

  function labelFrom(el) {
    if (!el || isPassword(el)) return "";
    for (const attr of ["aria-label", "title", "placeholder"]) {
      const text = sanitizeContextText(el.getAttribute(attr), contextLimit.targetLabel);
      if (text) return text;
    }
    const ids = (el.getAttribute("aria-labelledby") || "").split(/\s+/).slice(0, 3);
    for (const id of ids) {
      const text = textFrom(el.ownerDocument.getElementById(id), contextLimit.targetLabel);
      if (text) return text;
    }
    for (const label of Array.from(el.labels || []).slice(0, 2)) {
      const text = directText(label, contextLimit.targetLabel) || textFrom(label, contextLimit.targetLabel);
      if (text) return text;
    }
    if (!editable(el) && el.matches('button, a, label, legend, h1, h2, h3, h4, h5, h6, [role="button"], [role="heading"], [role="tab"]')) {
      const text = directText(el, contextLimit.targetLabel) || textFrom(el, contextLimit.targetLabel);
      if (text) return text;
    }
    const siblingLabel = el.previousElementSibling?.matches('label, dt, th, legend, [role="heading"]')
      ? (directText(el.previousElementSibling, contextLimit.targetLabel) || textFrom(el.previousElementSibling, contextLimit.targetLabel)) : '';
    if (siblingLabel) return siblingLabel;
    return sanitizeContextText(el.getAttribute("name"), contextLimit.targetLabel);
  }

  function nearestHeading(el) {
    let current = el;
    for (let depth = 0; current && depth < 6; depth++, current = current.parentElement) {
      const heading = current.matches('h1,h2,h3,h4,h5,h6,legend,[role="heading"]') ? current : current.querySelector(':scope > h1, :scope > h2, :scope > h3, :scope > h4, :scope > h5, :scope > h6, :scope > legend, :scope > [role="heading"]');
      const text = textFrom(heading, contextLimit.sectionLabel);
      if (text) return text;
    }
    return "";
  }

  function getFormLabel(el) {
    const form = el?.closest('form, [role="form"], [role="dialog"]');
    if (!form) return "";
    return sanitizeContextText(form.getAttribute("aria-label"), contextLimit.formLabel)
      || sanitizeContextText(form.getAttribute("title"), contextLimit.formLabel)
      || nearestHeading(form)
      || directText(form.querySelector('legend, [role="heading"], h1, h2, h3'), contextLimit.formLabel);
  }

  function getPageTitle(doc) { return sanitizeContextText(doc?.title, contextLimit.pageTitle); }

  function getItemTitle(doc, host = location.hostname) {
    const selectors = host.includes("mail.google.com")
      ? ['h2.hP', '[role="main"] h2', '[role="main"] [role="heading"]', '[data-thread-perm-id] h2']
      : host.includes("calendar.google.com")
        ? ['[role="dialog"] [role="heading"]', '[role="dialog"] h1', '[role="dialog"] h2']
        : ['[role="dialog"] [role="heading"]', '[aria-current="page"]', 'h1'];
    return firstVisibleText(doc, selectors, contextLimit.itemTitle);
  }

  function getSheetTabLabel(doc, host = location.hostname) {
    if (!host.includes("docs.google.com")) return "";
    return firstVisibleText(doc, [
      '[aria-label*="Sheet tabs"] [role="tab"][aria-selected="true"]',
      '[role="tablist"] [role="tab"][aria-selected="true"]',
    ], contextLimit.sectionLabel);
  }

  function nearbyText(el) {
    if (!el || el === el.ownerDocument.body || el === el.ownerDocument.documentElement) return "";
    const explicit = el.previousElementSibling?.matches('label, dt, th, legend, [role="heading"]')
      ? (directText(el.previousElementSibling, contextLimit.nearbyText) || textFrom(el.previousElementSibling, contextLimit.nearbyText)) : "";
    if (explicit) return explicit;
    const container = el.closest('fieldset, section, [role="region"], [role="dialog"], form');
    if (!container) return "";
    for (const attr of ["aria-label", "title"]) {
      const text = sanitizeContextText(container.getAttribute(attr), contextLimit.nearbyText);
      if (text) return text;
    }
    const heading = container.querySelector(':scope > legend, :scope > h1, :scope > h2, :scope > h3, :scope > h4, :scope > h5, :scope > h6, :scope > [role="heading"]');
    return directText(heading, contextLimit.nearbyText) || textFrom(heading, contextLimit.nearbyText);
  }

  function classifySemanticType(el, text) {
    const inputType = el?.isContentEditable ? "contenteditable" : el?.type || "";
    const value = `${text} ${el?.getAttribute?.("aria-label") || ""} ${el?.getAttribute?.("name") || ""}`.toLowerCase();
    if (inputType === "email" || /\b(email|e-mail|attendee)\b/.test(value)) return "email";
    if (inputType === "date" || inputType === "time" || /\b(date|time|when|start|end|schedule|duration)\b/.test(value)) return "datetime";
    if (inputType === "tel" || /\b(phone|mobile|telephone)\b/.test(value)) return "phone";
    if (inputType === "url" || /\b(url|website|link)\b/.test(value)) return "url";
    if (/\b(total|amount|price|cost|tax|subtotal|balance|expense|receipt|reimbursement|usd|dollar)\b/.test(value)) return "currency";
    if (/\b(quantity|qty|count|number|units)\b/.test(value) || inputType === "number") return "quantity";
    if (/\b(company|organization|vendor|client|account)\b/.test(value)) return "organization";
    if (/\b(name|person|contact|investor|attendee)\b/.test(value)) return "person";
    return "";
  }

  function extractSemanticContext(target) {
    const doc = elementOf(target)?.ownerDocument || document;
    const el = elementOf(target);
    if (el && isPassword(el)) return {};
    const context = { pageTitle: getPageTitle(doc) };
    const host = doc.location?.hostname || location.hostname;
    const itemTitle = getItemTitle(doc, host);
    const targetEl = el ? actionTarget(el) : null;
    const targetLabel = labelFrom(targetEl);
    const formLabel = el ? getFormLabel(el) : "";
    const sectionLabel = (el && getSheetTabLabel(doc, host)) || (el && nearestHeading(el)) || "";
    const nearby = nearbyText(targetEl || el);
    const semanticType = classifySemanticType(targetEl || el, `${targetLabel} ${formLabel} ${sectionLabel} ${itemTitle} ${nearby}`);
    if (itemTitle) context.itemTitle = itemTitle;
    if (sectionLabel) context.sectionLabel = sectionLabel;
    if (formLabel) context.formLabel = formLabel;
    if (targetLabel) context.targetLabel = targetLabel;
    if (nearby && nearby !== targetLabel && nearby !== sectionLabel) context.nearbyText = nearby;
    if (semanticType) context.semanticType = semanticType;
    return context;
  }

  function urlDetail(url, prefix) {
    const clean = sanitizeUrl(url);
    return clean ? { [`${prefix}Host`]: clean.host, [`${prefix}Path`]: clean.path } : {};
  }

  globalThis.MiaSemantics = Object.freeze({ elementOf, isPassword, editable, actionTarget, labelFrom, nearestHeading, getFormLabel, getItemTitle, getSheetTabLabel, classifySemanticType, extractSemanticContext, urlDetail });
})();
