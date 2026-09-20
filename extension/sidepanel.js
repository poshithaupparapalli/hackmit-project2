import { CONFIG } from './config.js';
const $ = selector => document.querySelector(selector);
let state, updating = false;
$('#open-dashboard').href = CONFIG.dashboardUrl;
async function send(kind, data = {}) {
  const response = await chrome.runtime.sendMessage({ kind, ...data });
  if (!response?.ok) throw new Error(response?.error || 'Mia is reconnecting. Reload the panel and try again.');
  return response.data;
}
function node(tag, text, className) {
  const element = document.createElement(tag);
  if (text !== undefined) element.textContent = text;
  if (className) element.className = className;
  return element;
}
function notify(text, error = false) {
  const message = $('#message'); message.textContent = text; message.hidden = false; message.classList.toggle('error', error);
}
async function action(button, work) {
  button.disabled = true;
  try { await work(); } catch (error) { notify(error.message, true); }
  finally { button.disabled = false; }
}
function time(value) { return value ? new Date(value).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' }) : 'Not yet'; }
function activityText(event) {
  const site = event.host === 'mail.google.com' ? 'Gmail' : event.host === 'docs.google.com' && event.path.startsWith('/spreadsheets') ? 'Google Sheets' : event.host;
  const context = event.context || {};
  const item = context.itemTitle || context.pageTitle;
  const target = context.targetLabel || event.detail?.targetName || event.detail?.name;
  if (event.type === 'nav' || event.type === 'tabopen') return `Opened ${item ? `"${item}" in ` : ''}${site}`;
  if (event.type === 'copy') return `Copied ${context.semanticType ? `${context.semanticType} ` : ''}value${target ? ` labeled "${target}"` : ''}${item ? ` from "${item}"` : ` from ${site}`}`;
  if (event.type === 'paste') return `Pasted${target ? ` into "${target}"` : ''}${item ? ` in "${item}"` : ` on ${site}`}`;
  if (event.type === 'edit') return `Updated${target ? ` "${target}"` : ''}${item ? ` in "${item}"` : ` on ${site}`}`;
  if (event.type === 'click') return `Interacted with${target ? ` "${target}"` : ''}${item ? ` in "${item}"` : ` on ${site}`}`;
  if (event.type === 'submit') return `Submitted${target ? ` "${target}"` : ' a form'}${item ? ` in "${item}"` : ` on ${site}`}`;
  const label = target || context.sectionLabel;
  const verbs = { tabclose: 'Closed a tab on', scroll: 'Read further on', focus: event.detail?.visible ? 'Focused' : 'Left', shortcut: 'Used a shortcut on' };
  return `${verbs[event.type] || event.type} ${site}${label ? ` · ${label}` : ''}`;
}
function renderState(data) {
  state = data;
  $('#observation-status').textContent = data.settings.paused ? 'Mia is paused' : 'Mia is observing';
  $('#observation-status').classList.toggle('paused', data.settings.paused);
  $('#brand-mark').classList.toggle('paused', data.settings.paused);
  $('#pause').textContent = data.settings.paused ? 'Resume' : 'Pause';
  $('#pause').disabled = false;
  $('#mode').hidden = !data.mock;
  $('#activity').replaceChildren(...data.recent.slice(-12).reverse().map(event => {
    const row = node('li'); row.append(node('time', time(event.timestamp)), node('span', activityText(event))); return row;
  }));
  $('#empty-activity').hidden = data.recent.length > 0;
  $('#domains').replaceChildren(...data.settings.excludedDomains.map(domain => {
    const row = node('li'), remove = node('button', '×'); remove.setAttribute('aria-label', `Stop excluding ${domain}`);
    remove.addEventListener('click', () => action(remove, async () => {
      await send('settings:update', { patch: { excludedDomains: state.settings.excludedDomains.filter(item => item !== domain) } }); await refreshState();
    }));
    row.append(node('span', domain), remove); return row;
  }));
  $('#debug').hidden = !data.debug;
  const entries = { 'Queued events': data.queueLength, 'Install identity': data.pendingIdentity ? 'Waiting for backend' : 'Ready', 'Last sync': time(data.lastFlushAt), 'Last analysis request': time(data.lastAnalyzeRequestAt), 'Next retry': data.retryAt ? time(data.retryAt) : 'Ready', 'Queue overflow': data.dropped, 'Backend': data.lastError || 'No errors', 'Rejected (retained)': data.rejected.length };
  $('#diagnostics').replaceChildren(...Object.entries(entries).flatMap(([key, value]) => [node('dt', key), node('dd', String(value))]));
  $('#events').textContent = JSON.stringify(data.recent, null, 2);
  if (data.dropped) notify(`Local queue is full: ${data.dropped} new observations could not be saved. Sync to make room.`, true);
}
async function refreshState() { if (!updating) renderState(await send('panel:state')); }
async function feedback(card, suggestion, decision, userEdits) {
  const buttons = [...card.querySelectorAll('button')]; buttons.forEach(button => button.disabled = true);
  try {
    await send('suggestions:feedback', { id: suggestion.id, decision, ...(decision === 'edit' ? { userEdits } : {}) });
    notify(decision === 'accept' ? 'Accepted. Nothing will run until you explicitly run it in the workflows app.' : decision === 'dismiss' ? 'Proposal dismissed.' : 'Your correction was saved for future analysis.');
    await refreshSuggestions();
  } catch (error) { notify(error.message, true); buttons.forEach(button => button.disabled = false); }
}
function renderSuggestion(suggestion) {
  const card = node('article', undefined, 'card');
  card.append(node('div', suggestion.kind === 'rule' ? 'I THINK I LEARNED A RULE' : 'A LITTLE LESS REPETITION', 'eyebrow'), node('h3', suggestion.title), node('p', suggestion.summary));
  if (Array.isArray(suggestion.evidence)) {
    const list = node('ul'); list.append(...suggestion.evidence.slice(0, 3).map(text => node('li', text))); card.append(list);
  }
  if (Array.isArray(suggestion.steps) && suggestion.steps.length) {
    const list = node('ol'); list.append(...suggestion.steps.map(text => node('li', text))); card.append(list);
  }
  if (suggestion.kind === 'rule') { card.append(node('p', `When: ${suggestion.trigger || ''}`), node('p', `Rule: ${suggestion.action || ''}`)); }
  if (Number.isFinite(suggestion.confidence)) card.append(node('p', `${Math.round(Math.max(0, Math.min(1, suggestion.confidence)) * 100)}% confidence${Number.isFinite(suggestion.timeSavedPerWeekMinutes) ? ` · about ${suggestion.timeSavedPerWeekMinutes} min / week` : ''}`, 'confidence'));
  const details = node('a', 'See details →', 'quiet card-links');
  details.href = `${CONFIG.dashboardUrl}?suggestion=${encodeURIComponent(suggestion.id)}`;
  details.target = '_blank'; details.rel = 'noopener';
  card.append(details);
  const actions = node('div', undefined, 'actions');
  if (suggestion.status === 'proposed') {
    const yes = node('button', suggestion.kind === 'rule' ? "That's right" : 'Yes', 'primary');
    const no = node('button', suggestion.kind === 'rule' ? 'Not a rule' : 'No');
    const edit = node('button', 'I have edits');
    yes.addEventListener('click', () => feedback(card, suggestion, 'accept'));
    no.addEventListener('click', () => feedback(card, suggestion, 'dismiss'));
    edit.addEventListener('click', () => {
      if (card.querySelector('textarea')) { card.querySelector('textarea').focus(); return; }
      const form = node('form'), label = node('label', 'What should Mia change?'), input = node('textarea');
      input.id = `edit-${suggestion.id}`; label.htmlFor = input.id; input.required = true; input.maxLength = 2000;
      input.placeholder = 'Only do this for reimbursement receipts over $25.';
      const save = node('button', 'Save correction', 'primary'); save.type = 'submit';
      form.append(label, input, save);
      form.addEventListener('submit', event => { event.preventDefault(); if (input.value.trim()) feedback(card, suggestion, 'edit', input.value.trim()); });
      card.append(form); input.focus();
    });
    actions.append(yes, no, edit);
  } else {
    actions.append(node('span', suggestion.status === 'accepted' ? 'Accepted · ready for your next decision' : suggestion.status, 'muted'));
    if (suggestion.status === 'dismissed') {
      const restore = node('button', 'Restore'); restore.addEventListener('click', () => action(restore, async () => { await send('suggestions:restore', { id: suggestion.id }); await refreshSuggestions(); })); actions.append(restore);
    }
  }
  card.append(actions); return card;
}
async function refreshSuggestions() {
  const suggestions = await send('suggestions:get');
  $('#suggestions').replaceChildren(...(suggestions.length ? suggestions.filter(item => item && typeof item.id === 'string').map(renderSuggestion) : [node('p', 'Nothing to propose yet. Mia is looking for repeated patterns.', 'empty')]));
  $('#brand-badge').hidden = !suggestions.some(item => item?.status === 'proposed');
}
$('#pause').addEventListener('click', () => action($('#pause'), async () => {
  updating = true;
  try { await send('settings:update', { patch: { paused: !state.settings.paused } }); }
  finally { updating = false; }
  await refreshState();
}));
$('#domain-form').addEventListener('submit', event => {
  event.preventDefault(); action($('#domain-form button'), async () => {
    const domain = $('#domain').value.trim();
    await send('settings:update', { patch: { excludedDomains: [...state.settings.excludedDomains, domain] } });
    $('#domain').value = ''; await refreshState();
  });
});
$('#refresh').addEventListener('click', () => action($('#refresh'), refreshSuggestions));
$('#flush').addEventListener('click', () => action($('#flush'), async () => { await send('queue:flush'); await refreshState(); await refreshSuggestions(); }));
await refreshState().catch(error => notify(error.message, true));
await refreshSuggestions().catch(error => { $('#suggestions').replaceChildren(node('p', 'Proposals are unavailable. Your local observations are kept while Mia reconnects.', 'empty')); notify(error.message, true); });
// Timers are only UI refreshes; durable ingestion scheduling uses Chrome alarms.
setInterval(() => refreshState().catch(() => {}), 2000);
setInterval(() => { if (!document.querySelector('textarea')) refreshSuggestions().catch(() => {}); }, 30000);
