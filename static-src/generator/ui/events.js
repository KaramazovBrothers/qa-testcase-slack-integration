import { $, checked, state } from '../store.js';
import { translate } from '../translations/translations.js';
import { amountInputIds, generateCases, validAmountInput } from '../cases/index.js';
import { renderCases, caseCopyText, copyText } from '../cases/render.js';
import { updatePayoutAmount, updateUI } from '../cases/payout.js';
import { mentionPayload, renderMentions, addMention, resetMentions } from './mentions.js';
import { refreshLanguage } from './language.js';
import { loadAccounts, setAccountOptions, bindAccountPickers, saveStandaloneAccounts } from './accounts.js';

/** Replace the placeholder tokens with the real operator-entered values. */
function localise(text, protectedValues) {
  return translate(text).replace(/⟦VALUE(\d+)⟧/g, (_, i) => protectedValues[Number(i)]);
}

/** Generate cases from the current form, honouring the workspace gates. */
export function generate() {
  if (state.workspaceHooks?.beforeGenerate && !state.workspaceHooks.beforeGenerate()) return;
  try {
    state.protectedValues = [];
    state.protectValues = true;
    let cases;
    try {
      cases = generateCases();
    } finally {
      state.protectValues = false;
    }

    const kinds = cases.map((item) => (item.usd || /^USD -/.test(item.title) ? 'usd' : 'main'));
    cases = cases.map((item) => ({ title: localise(item.title, state.protectedValues), text: localise(item.text, state.protectedValues) }));
    renderCases(cases);
    state.generated = true;

    if (state.workspaceHooks) {
      state.workspaceHooks.onGenerated(
        undefined,
        window.qaGenerator.cases().map((item, i) => ({ ...item, account_kind: kinds[i] })),
      );
    }
    $('message').textContent = '';
  } catch (error) {
    state.protectValues = false;
    $('message').textContent = translate('Ошибка генератора: ') + error.message;
  }
}

/** Copy all cases as one text blob. */
export function copyAllCases() {
  const text = [...state.root.querySelectorAll('.case')].map(caseCopyText).join('\n\n================\n\n');
  if (!text) {
    $('message').textContent = translate('Сначала сгенерируйте кейсы.');
    return;
  }
  copyText(text, $('message'), $('output'));
}

/** Send every case (optionally skipping the first) to Slack. */
export async function sendCasesToSlack(skipFirst = false) {
  const caseNodes = [...state.root.querySelectorAll('.case')];
  if (!caseNodes.length) {
    $('message').textContent = translate('Сначала сгенерируйте кейсы.');
    return;
  }
  const cases = caseNodes.slice(skipFirst ? 1 : 0).map((node) => readCaseFromNode(node));
  if (!cases.length) {
    $('message').textContent = translate('Нет кейсов для отправки после первого.');
    return;
  }
  $('message').textContent = translate('Отправляем кейсы в Slack...');
  try {
    const response = await fetch('/slack/send-cases', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ region: $('region').value, cases, ...mentionPayload() }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || 'Slack send failed');
    $('message').textContent = translate('Отправлено в Slack: ') + data.sent + translate(' кейс(ов).');
  } catch (error) {
    $('message').textContent = translate('Ошибка отправки в Slack: ') + error.message;
  }
}

function readCaseFromNode(card) {
  return {
    title: card.querySelector('h3').textContent,
    text: card.querySelector('pre').textContent,
    comment: card.querySelector('.case-comment').value.trim(),
    request_text: card.querySelector('.case-request').value.trim(),
  };
}

/** Number inputs reject anything that is not 0–6 digits. */
function bindAmountInputs() {
  amountInputIds.forEach((id) => {
    const input = $(id);
    let previous = input.value;
    input.addEventListener('input', () => {
      if (!validAmountInput(input.value)) {
        input.value = validAmountInput(previous) ? previous : '';
        $('message').textContent = translate('Введите целое число: не более 6 цифр.');
      } else {
        previous = input.value;
      }
    });
    input.addEventListener('beforeinput', () => { previous = input.value; });
    input.addEventListener('paste', (event) => {
      const text = event.clipboardData.getData('text');
      const next = input.value.slice(0, input.selectionStart) + text + input.value.slice(input.selectionEnd);
      if (!validAmountInput(next)) {
        event.preventDefault();
        $('message').textContent = translate('Введите целое число: не более 6 цифр.');
      }
    });
  });
}

/** Image lightbox for the Cashdesk screenshots. */
function bindLightbox() {
  const dialog = state.root.querySelector('dialog');
  let opener = null;
  state.root.querySelectorAll('.thumbnail').forEach((button) => {
    button.addEventListener('click', () => {
      opener = button;
      const image = button.querySelector('img');
      const large = dialog.querySelector('img');
      large.src = image.src;
      large.alt = image.alt;
      dialog.showModal();
    });
  });
  dialog.querySelector('button').addEventListener('click', () => dialog.close());
  dialog.addEventListener('click', (event) => { if (event.target === dialog) dialog.close(); });
  dialog.addEventListener('close', () => { if (opener) opener.focus(); });
}

/** Region switch: confirm, clear credentials and reload the catalog. */
function bindRegionSwitch() {
  $('region').addEventListener('input', renderMentions);
  $('region').addEventListener('input', () => {
    const previous = state.accountRegion;
    const region = $('region').value;
    if (previous === region) return;
    if (state.workspaceHooks?.beforeRegionChange && !state.workspaceHooks.beforeRegionChange(previous)) {
      $('region').value = previous;
      updateUI();
      renderMentions();
      return;
    }
    state.accountRegion = region;
    for (const id of ['account', 'login', 'password', 'usdAccount', 'usdLogin', 'usdPassword']) $(id).value = '';
    setAccountOptions([]);
    if (state.workspaceHooks?.onRegionChange) state.workspaceHooks.onRegionChange(region);
    else loadAccounts().catch(accountErrorBridge);
  });
}

function accountErrorBridge(error) {
  state.root.querySelector('.account-save-status').textContent = error.message;
}

/** Attach every DOM listener that the legacy generator registered inline. */
export function bindEvents() {
  bindAmountInputs();

  $('payoutFeeAmount').addEventListener('input', () => { state.payoutFeeManual = true; });
  $('payoutAmount').addEventListener('input', () => { updatePayoutAmount(); });
  $('generate').addEventListener('click', generate);

  $('sendSlack').addEventListener('click', () => sendCasesToSlack());
  $('sendSlackExceptFirst').addEventListener('click', () => sendCasesToSlack(true));
  $('copyAll').addEventListener('click', copyAllCases);

  // Any form change invalidates generated output until the next generation.
  state.root.querySelectorAll('input,select').forEach((el) => el.addEventListener('input', () => {
    updateUI();
    $('regionInfo').innerHTML = translate($('regionInfo').innerHTML);
    if (state.generated) {
      $('output').textContent = '';
      $('count').textContent = '0';
      $('message').textContent = translate('Настройки изменены. Сгенерируйте кейсы заново.');
      state.generated = false;
    }
  }));

  state.root.querySelectorAll('[data-lang]').forEach((button) => button.addEventListener('click', () => {
    state.language = button.dataset.lang;
    refreshLanguage();
    if (state.generated) generate();
  }));

  bindLightbox();
  bindRegionSwitch();
  bindAccountPickers();

  state.root.querySelector('.standalone-account-save').addEventListener('click', saveStandaloneAccounts);
  $('addMention').addEventListener('click', addMention);
  $('resetMentions').addEventListener('click', resetMentions);
}
