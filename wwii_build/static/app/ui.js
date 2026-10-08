// Shared UI pieces: toasts, the offline banner, state pills.
import { h } from './dom.js';

let stateLabels = {};

export function setStateLabels(labels) {
  stateLabels = labels || {};
}

export function stateLabel(state) {
  return stateLabels[state] || state || 'לא ידוע';
}

export function pill(state, label) {
  return h('span', { class: `pill s-${state || 'UNKNOWN'}`, title: state || 'UNKNOWN' }, label || stateLabel(state));
}

/** The 'web' badge of a task that opted in to web research (extra.allow_web), or of an attempt that ran with web. */
export function webBadge() {
  return h('span', { class: 'pill s-WEB', title: 'מחקר עם גישה לרשת (allow_web)' }, 'web');
}

/** A toast with the action.result message; errors stay longer. Click to dismiss. */
export function toast(message, ok = true) {
  const box = document.getElementById('toasts');
  if (!box || !message) return;
  const el = h('div', { class: `toast ${ok ? 'ok' : 'bad'}`, role: ok ? 'status' : 'alert' }, message);
  const remove = () => el.remove();
  el.addEventListener('click', remove);
  box.append(el);
  while (box.children.length > 5) box.firstChild.remove();
  setTimeout(remove, ok ? 6000 : 12000);
}

export function setOffline(offline) {
  const banner = document.getElementById('offline-banner');
  if (banner) banner.hidden = !offline;
}
