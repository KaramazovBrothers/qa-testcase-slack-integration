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
    input.maxLength = 80;
    input.placeholder = '@username / U0123456789';
    input.setAttribute('aria-label', translate('Человек для тега') + ' ' + (index + 1));
    input.addEventListener('input', () => {
      state.mentionEdits[region][index] = input.value;
      refreshCaseTags();
    });

    const remove = document.createElement('button');
    remove.type = 'button';
    remove.className = 'secondary';
    remove.textContent = translate('Исключить');
    remove.addEventListener('click', () => {
      state.mentionEdits[region].splice(index, 1);
      renderMentions();
    });

    row.append(input, remove);
    list.appendChild(row);
  });

  refreshCaseTags();
  $('mentionStatus').textContent = state.mentionEdits[region].length
    ? ''
    : translate('Никто не будет отмечен.');
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
