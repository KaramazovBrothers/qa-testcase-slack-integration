import { $, state } from '../store.js';

/** Region account catalog operations against the local API. */

export function accountError(error) {
  state.root.querySelector('.account-save-status').textContent = error.message;
}

const fieldsFor = (kind) => (kind === 'usd'
  ? ['usdAccount', 'usdLogin', 'usdPassword']
  : ['account', 'login', 'password']);

/** Replace every saved-user dropdown with the catalog for the current region. */
export function setAccountOptions(accounts) {
  state.accountOptions = accounts;
  state.accountRegion = $('region').value;
  for (const select of state.root.querySelectorAll('.account-picker')) {
    const ids = fieldsFor(select.dataset.accountKind);
    select.replaceChildren(new Option('Новый пользователь · ввести вручную', ''));
    for (const account of accounts) {
      select.add(new Option(`${account.name} · ${account.account_id || account.login || 'без ID'}`, account.id));
    }
    const match = accounts.find((account) => [account.account_id, account.login, account.password]
      .every((value, i) => value === $(ids[i]).value));
    select.value = match?.id || '';
  }
}

/** Load the owner's catalog for a region; stale responses are ignored. */
export async function loadAccounts() {
  const revision = ++state.accountRequest;
  const region = $('region').value;
  const response = await fetch('/api/tasks/accounts?region=' + encodeURIComponent(region));
  if (!response.ok) throw new Error('Не удалось загрузить пользователей региона');
  const accounts = await response.json();
  if (revision === state.accountRequest && region === $('region').value) setAccountOptions(accounts);
  return accounts;
}

/** Wire the saved-user dropdowns to the credential inputs. */
export function bindAccountPickers() {
  for (const select of state.root.querySelectorAll('.account-picker')) {
    const ids = fieldsFor(select.dataset.accountKind);

    select.addEventListener('change', () => {
      const account = state.accountOptions.find((item) => item.id === select.value);
      const values = account ? [account.account_id, account.login, account.password] : ['', '', ''];
      ids.forEach((id, i) => { $(id).value = values[i]; });
      $(ids[0]).dispatchEvent(new Event('input', { bubbles: true }));
      select.value = account?.id || '';
    });

    for (const id of ids) {
      $(id).addEventListener('input', () => {
        const account = state.accountOptions.find((item) => [item.account_id, item.login, item.password]
          .every((value, i) => value === $(ids[i]).value));
        select.value = account?.id || '';
      });
    }
  }
}

/** Persist the credentials typed into the form for the current region. */
export async function saveStandaloneAccounts() {
  const button = state.root.querySelector('.standalone-account-save');
  button.disabled = true;
  try {
    const users = [];
    for (const kind of ['main', 'usd']) {
      if (kind === 'usd' && $('license').value !== 'com') continue;
      const ids = fieldsFor(kind);
      const values = ids.map((id) => $(id).value);
      if (!values.some(Boolean)) continue;
      const existing = state.accountOptions.find((item) => [item.account_id, item.login, item.password]
        .every((value, i) => value === values[i]));
      users.push({
        id: existing?.id || crypto.randomUUID(),
        name: existing?.name || values[1] || values[0] || 'Пользователь',
        kind,
        account_id: values[0],
        login: values[1],
        password: values[2],
      });
    }
    const response = await fetch('/api/tasks/accounts', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ region: $('region').value, test_accounts: users }),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : 'Проверьте данные пользователя');
    setAccountOptions(result.accounts);
    state.root.querySelector('.account-save-status').textContent = 'Пользователи региона сохранены';
  } catch (error) {
    accountError(error);
  } finally {
    button.disabled = false;
  }
}

/** Copy a saved user's credentials into the form, for workspace sync. */
export function syncAccountFields(previous, next) {
  for (const ids of [['account', 'login', 'password'], ['usdAccount', 'usdLogin', 'usdPassword']]) {
    const keys = ['account_id', 'login', 'password'];
    if (ids.every((id, i) => $(id).value === previous[keys[i]])) {
      ids.forEach((id, i) => { $(id).value = next[keys[i]]; });
    }
  }
}
