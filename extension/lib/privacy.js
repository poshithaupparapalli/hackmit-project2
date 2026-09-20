/* Privacy and canonical-shape helpers shared by the content script and worker.
 * Context is intentionally richer now, but it is still bounded and fail-closed:
 * callers pass structural labels/titles, never input values or page dumps. */
(() => {
  const CONTEXT_LIMITS = Object.freeze({ pageTitle: 200, itemTitle: 200, sectionLabel: 120, formLabel: 120, targetLabel: 120, nearbyText: 200, semanticType: 32 });
  const SECRET_PATTERNS = [
    /-----BEGIN [^-]*PRIVATE KEY-----/i,
    /\b(?:bearer|authorization|access[_ -]?token|refresh[_ -]?token|session[_ -]?token|api[_ -]?key|secret)\s*[:=]?\s*[A-Za-z0-9._~+/=-]{8,}/i,
    /\b(?:secret|password|confidential)(?:[_ -][A-Za-z0-9]+)+\b/i,
    /\bsk-[A-Za-z0-9_-]{12,}\b/i,
    /\b\d{3}-\d{2}-\d{4}\b/,
  ];
  const CARD_DIGITS = /(?:\d[ -]?){13,19}/g;
  const SEMANTIC_TYPES = new Set(["currency", "email", "datetime", "person", "organization", "phone", "address", "quantity", "url", "identifier", "text"]);

  function likelyCardNumber(value) {
    const digits = String(value).replace(/\D/g, "");
    if (digits.length < 13 || digits.length > 19) return false;
    let sum = 0, alternate = false;
    for (let i = digits.length - 1; i >= 0; i--) {
      let n = Number(digits[i]);
      if (alternate && (n *= 2) > 9) n -= 9;
      sum += n; alternate = !alternate;
    }
    return sum % 10 === 0;
  }

  function hasSecret(value) {
    if (SECRET_PATTERNS.some(pattern => pattern.test(value))) return true;
    return [...value.matchAll(CARD_DIGITS)].some(match => likelyCardNumber(match[0]));
  }

  function sanitizeContextText(value, max = 80) {
    if (typeof value !== "string") return "";
    const normalized = value.replace(/[\u0000-\u001f\u007f]/g, " ").replace(/\s+/g, " ").trim();
    if (!normalized || hasSecret(normalized)) return "";
    if (normalized.length <= max) return normalized;
    const clipped = normalized.slice(0, max + 1).replace(/\s+\S*$/, "").trim();
    return clipped || normalized.slice(0, max);
  }

  // Kept for existing callers/details; richer context uses explicit limits.
  const sanitizeText = (value, max = 80) => sanitizeContextText(value, max);

  function sanitizeUrl(value) {
    try {
      const url = new URL(value);
      if (!["http:", "https:"].includes(url.protocol)) return null;
      return { host: url.hostname.toLowerCase(), path: url.pathname.slice(0, 500) };
    } catch { return null; }
  }

  function normalizeDomain(value) {
    if (typeof value !== "string") return null;
    const trimmed = value.trim().toLowerCase();
    try {
      const url = new URL(trimmed.includes("://") ? trimmed : `https://${trimmed}`);
      if (!sanitizeUrl(url.href) || url.username || url.password || url.search || url.hash || !["", "/"].includes(url.pathname)) return null;
      const host = url.hostname.replace(/\.$/, "");
      return /^[a-z0-9.-]+$/.test(host) && !host.includes("..") ? host : null;
    } catch { return null; }
  }

  function isExcludedDomain(host, domains) {
    host = host.toLowerCase().replace(/\.$/, "");
    return domains.some(domain => host === domain || host.endsWith(`.${domain}`));
  }

  const fields = {
    nav: { referrerHost: "host" },
    click: { tag: "tag", role: "role", label: "label", hrefHost: "host", hrefPath: "path" },
    edit: { tag: "tag", inputType: "input", name: "label", length: "number" },
    submit: { name: "label", actionHost: "host", actionPath: "path", fieldCount: "number", via: "via" },
    copy: { length: "number", wordCount: "number" },
    paste: { length: "number", targetTag: "tag", targetName: "label" },
    shortcut: { key: "key" }, scroll: { depth: "depth" }, focus: { visible: "boolean" }, tabopen: {}, tabclose: {},
  };

  function cleanField(value, kind) {
    if (kind === "number") return Number.isSafeInteger(value) && value >= 0 ? value : undefined;
    if (kind === "boolean") return typeof value === "boolean" ? value : undefined;
    if (kind === "depth") return [25, 50, 75, 100].includes(value) ? value : undefined;
    if (typeof value !== "string") return undefined;
    if (kind === "label") return sanitizeContextText(value, 80) || undefined;
    if (kind === "host") return /^[a-z0-9.-]+$/.test(value) ? value.slice(0, 253) : undefined;
    if (kind === "path") return value.startsWith("/") ? value.split(/[?#]/)[0].slice(0, 500) : undefined;
    const allowed = {
      tag: ["A", "BUTTON", "INPUT", "TEXTAREA", "SELECT", "FORM", "DIV", "SPAN", "TD", "TH", "LABEL", "SVG", "BODY"],
      role: ["button", "link", "textbox", "combobox", "checkbox", "radio", "menuitem", "tab", "gridcell", "heading", "dialog"],
      input: ["text", "email", "number", "search", "tel", "url", "date", "time", "checkbox", "radio", "select", "textarea", "contenteditable", "file", "range", "hidden"],
      via: ["button", "enter", "unknown"],
      key: ["Copy", "Paste", "Cut", "Select all", "Undo", "Redo", "Find", "Save"],
    };
    return allowed[kind]?.includes(value) ? value : undefined;
  }

  function cleanContext(raw) {
    const context = {};
    for (const [key, max] of Object.entries(CONTEXT_LIMITS)) {
      let value = raw?.[key];
      if (key === "semanticType") {
        value = typeof value === "string" ? value.toLowerCase().trim() : "";
        if (!SEMANTIC_TYPES.has(value)) value = "";
      } else value = sanitizeContextText(value, max);
      if (value) context[key] = value;
    }
    return context;
  }

  function sanitizeObservation(raw) {
    if (!raw || !Object.hasOwn(fields, raw.type) || raw.detail?.inputType === "password") return null;
    const detail = {};
    for (const [key, kind] of Object.entries(fields[raw.type])) {
      const value = cleanField(raw.detail?.[key], kind);
      if (value !== undefined) detail[key] = value;
    }
    const context = cleanContext(raw.context);
    return { type: raw.type, detail, ...(Object.keys(context).length ? { context } : {}) };
  }

  globalThis.MiaPrivacy = Object.freeze({ CONTEXT_LIMITS, sanitizeText, sanitizeContextText, sanitizeUrl, normalizeDomain, isExcludedDomain, sanitizeObservation, cleanContext, hasSecret });
})();
