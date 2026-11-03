import { $, state } from '../store.js';
import { translate } from '../translations/translations.js';

/** Region key currently shown in the form. */
const regionKey = () => $('region').value;

/** Non-empty, trimmed mentions for the selected region. */
export function selectedMentions() {
  if (!state.mentionDefaults) throw new Error(translate('Список людей ещё не загружен.'));
  return (state.mentionEdits[regionKey()] || []).map((name) => name.trim()).filter(Boolean);
}

/** Payload fragment consumed by `/slack/send-cases`. */
export function mentionPayload() {
  return {
    mention_users: selectedMentions(),
    operation: $('integration').value === 'payout' ? 'payout' : 'deposit',
  };
}

/** Refresh the tag preview rendered above each case. */
export function refreshCaseTags() {
  const text = selectedMentionsSafely().join(' ');
  state.root.querySelectorAll('.case-tags').forEach((node) => { node.textContent = text; });
}

function selectedMentionsSafely() {
  return (state.mentionEdits[regionKey()] || []).map((name) => name.trim()).filter(Boolean);
}

/** Rebuild the editable mention list for the selected region. */
export function renderMentions() {
  refreshCaseTags();
  const region = regionKey();
  const list = $('mentionList');
  list.textContent = '';
  if (!state.mentionDefaults) return;
  if (!Object.hasOwn(state.mentionEdits, region)) {
    state.mentionEdits[region] = [...(state.mentionDefaults[region] || [])];
  }

  state.mentionEdits[region].forEach((name, index) => {
    const row = document.createElement('div');
    row.className = 'mention-row';

    const input = document.createElement('input');
    input.value = name;
    input.maxLength = 300;
    input.placeholder = translate('Ссылка на профиль, U0123456789 или @username');
    input.setAttribute('aria-label', translate('Человек для тега') + ' ' + (index + 1));
    input.addEventListener('input', () => {
      state.mentionEdits[region][index] = input.value;
      refreshCaseTags();
    });
    // Pasting a profile link is the easy path; resolve it once the field blurs.
    input.addEventListener('blur', () => {
      resolveMentionRow(region, index, input);
    });

    const remove = document.createElement('button');
    remove.type = 'button';
    remove.className = 'secondary';
    remove.textContent = translate('Исключить');
    remove.addEventListener('click', () => {
      state.mentionEdits[region].splice(index, 1);
      renderMentions();
    });

    const label = document.createElement('span');
    label.className = 'mention-name';
    label.textContent = personLabel(name);

    row.append(input, label, remove);
    list.appendChild(row);
  });

  refreshCaseTags();
  $('mentionStatus').textContent = state.mentionEdits[region].length
    ? ''
    : translate('Никто не будет отмечен.');
}

/** Cached name for a stored value, falling back to the raw value. */
function personLabel(value) {
  const id = mentionId(value);
  return (id && state.slackPeople && state.slackPeople[id]) || value;
}

/** Pull `U…` out of a value the user typed, so labels survive a paste. */
function mentionId(value) {
  const match = String(value || '').match(/(?:^|\/team\/|^@|<@)([UW][A-Z0-9]{2,})/);
  return match ? match[1] : null;
}

/** Replace a pasted link with the member ID and remember the readable name. */
async function resolveMentionRow(region, index, input) {
  const value = input.value.trim();
  if (!value) return;
  try {
    const response = await fetch('/api/slack/people', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ entries: [value] }),
    });
    if (!response.ok) return;
    const data = await response.json();
    const person = data.people && data.people[0];
    if (!person) return;
    state.slackPeople = { ...(state.slackPeople || {}), ...(data.names || {}) };
    if (person.id !== value) {
      state.mentionEdits[region][index] = person.id;
      input.value = person.id;
      refreshCaseTags();
    }
    const label = input.parentElement && input.parentElement.querySelector('.mention-name');
    if (label) label.textContent = person.label;
  } catch (error) {
    // Keep the typed value; sending validates it with a readable message.
  }
}

/** Append an empty mention row, if the defaults are loaded. */
export function addMention() {
  if (!state.mentionDefaults) return;
  const region = regionKey();
  if (!Object.hasOwn(state.mentionEdits, region)) state.mentionEdits[region] = [];
  state.mentionEdits[region].push('');
  renderMentions();
}

/** Drop local edits so the region defaults are restored on next render. */
export function resetMentions() {
  delete state.mentionEdits[regionKey()];
  renderMentions();
}

/** Load the versioned per-region default list from the backend. */
export async function loadMentions() {
  try {
    const response = await fetch('/api/region-mentions');
    if (!response.ok) throw new Error('region mentions unavailable');
    const data = await response.json();
    const valid = data && typeof data === 'object' && !Array.isArray(data)
      && Object.values(data).every((names) => Array.isArray(names) && names.every((name) => typeof name === 'string'));
    if (!valid) throw new Error('invalid region mentions payload');
    state.mentionDefaults = data;
    renderMentions();
  } catch {
    $('mentionStatus').textContent = translate('Не удалось загрузить список людей. Обновите страницу.');
  }
}
