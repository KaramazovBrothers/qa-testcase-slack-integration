import { state } from '../store.js';
import { generateCases } from '../cases/index.js';
import { renderMentions, loadMentions, addMention, resetMentions, mentionPayload } from './mentions.js';
import { cacheStaticNodes, refreshLanguage } from './language.js';
import {
  accountError, setAccountOptions, loadAccounts, syncAccountFields, bindAccountPickers,
} from './accounts.js';
import { readCase } from '../cases/render.js';

/** Inputs captured at start so `restore()` can reset every field. */
let workspaceFields = [];
let initialFields = {};

/**
 * Public adapter used by the QA workspace iframe.
 * The contract is unchanged from the legacy generator — the workspace relies
 * on `ready`, `configure`, `snapshot`, `restore` and `cases`.
 */
export function installWorkspaceApi() {
  workspaceFields = [...state.root.querySelectorAll('input[data-id],select[data-id],textarea[data-id]')];
  initialFields = Object.fromEntries(workspaceFields.map((el) => [
    el.dataset.id,
    el.type === 'checkbox' ? el.checked : el.value,
  ]));

  window.qaGenerator = {
    configure(hooks) {
      state.workspaceHooks = hooks;
      state.root.querySelector('.standalone-account-save').hidden = true;
      ['output', 'copyAll', 'sendSlack', 'sendSlackExceptFirst'].forEach((id) => {
        const node = state.root.querySelector(`[data-id="${id}"]`);
        if (node) node.hidden = true;
      });
    },
    setAccountOptions,
    loadAccounts,
    syncAccount: syncAccountFields,
    lockRegion(locked) {
      const region = state.root.querySelector('[data-id="region"]');
      if (region) region.disabled = !!locked;
    },
    snapshot() {
      return {
        fields: Object.fromEntries(workspaceFields.map((el) => [
          el.dataset.id,
          el.type === 'checkbox' ? el.checked : el.value,
        ])),
        language: state.language,
        payout_fee_manual: state.payoutFeeManual,
        mention_edits: JSON.parse(JSON.stringify({
          [state.root.querySelector('[data-id="region"]').value]:
            state.mentionEdits[state.root.querySelector('[data-id="region"]').value] || [],
        })),
      };
    },
    restore(settings = {}) {
      const fields = { ...initialFields, ...(settings.fields || {}) };
      workspaceFields.forEach((el) => {
        if (el.type === 'checkbox') el.checked = fields[el.dataset.id];
        else el.value = fields[el.dataset.id];
      });
      state.language = settings.language || 'ru';
      state.payoutFeeManual = !!settings.payout_fee_manual;
      Object.keys(state.mentionEdits).forEach((key) => delete state.mentionEdits[key]);
      Object.assign(state.mentionEdits, JSON.parse(JSON.stringify(settings.mention_edits || {})));
      state.generated = false;
      const output = state.root.querySelector('[data-id="output"]');
      const count = state.root.querySelector('[data-id="count"]');
      const message = state.root.querySelector('[data-id="message"]');
      if (output) output.textContent = '';
      if (count) count.textContent = '0';
      if (message) message.textContent = '';
      refreshLanguage();
    },
    cases() {
      return [...state.root.querySelectorAll('.case')].map(readCase);
    },
    result() {
      return {
        cases: this.cases(),
        region: state.root.querySelector('[data-id="region"]').value,
        ...mentionPayload(),
      };
    },
  };
}

/** Boot the generator inside its container element. */
export function start(root) {
  state.root = root;
  cacheStaticNodes();
  refreshLanguage();
  root.dataset.ready = '1';
  window.qaGenerator.ready = Promise.all([
    loadMentions(),
    loadAccounts().catch(accountError),
  ]);
}

// Re-exported for the workspace adapter and tests.
export { generateCases, renderMentions, addMention, resetMentions };
