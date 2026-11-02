/**
 * Behavioural tests for the generator modules.
 *
 * The generator reads its form through `state.root.querySelector`, so a tiny
 * fake DOM is enough: we only need `[data-id]` lookups, `select` option
 * population and classList toggling used by `updateUI`.
 */

const elements = new Map();

class FakeClassList {
  constructor() { this.set = new Set(); }
  toggle(name, force) {
    const on = force === undefined ? !this.set.has(name) : !!force;
    if (on) this.set.add(name); else this.set.delete(name);
    return on;
  }
  add(name) { this.set.add(name); }
  contains(name) { return this.set.has(name); }
}

function makeElement(id, value = '', type = 'text') {
  const el = {
    id,
    value,
    checked: false,
    type,
    dataset: { id },
    classList: new FakeClassList(),
    style: {},
    textContent: '',
    innerHTML: '',
    children: [],
    addEventListener() {},
    replaceChildren() { this.children = []; },
    append(...nodes) { this.children.push(...nodes); },
    appendChild(node) { this.children.push(node); return node; },
    add(option) { this.children.push(option); },
    querySelector() { return null; },
    focus() {},
    setAttribute() {},
  };
  elements.set(id, el);
  return el;
}

const root = {
  dataset: {},
  querySelector(selector) {
    const match = /\[data-id="([^"]+)"\]/.exec(selector);
    return match ? elements.get(match[1]) || null : null;
  },
  querySelectorAll() { return []; },
};

export function resetForm(values = {}) {
  elements.clear();
  const defaults = {
    integration: 'HPP',
    license: 'pinco',
    region: 'TR',
    wallet: 'standard',
    amountChange: 'no',
    cardNetwork: 'visa',
    googleMethodMode: 'shared',
    qrScanner: 'camera',
    qrMobile: 'button',
    site: 'https://test.site/',
    method: 'TEST_METHOD',
    nativeMethod: 'NATIVE_METHOD',
    account: 'ACC-1',
    login: 'user@test',
    password: 'secret',
    usdAccount: 'USD-ACC',
    usdLogin: 'usd@test',
    usdPassword: 'usd-secret',
    amount: '100',
    overRequest: '110',
    overPaid: '120',
    underRequest: '90',
    underPaid: '80',
    usdAmount: '50',
    usdOverRequest: '60',
    usdUnderRequest: '40',
    usdOverPaid: '70',
    usdUnderPaid: '30',
    payoutAmount: '1000',
    payoutFeeAmount: '1331',
    message: '',
    payoutWarning: '',
    ...values,
  };
  for (const [id, value] of Object.entries(defaults)) makeElement(id, value);
  for (const id of ['qr', 'receipt', 'oneClick', 'timer', 'cancel', 'returnToCashier']) {
    makeElement(id, '', 'checkbox');
  }
  for (const id of ['walletWrap', 'amountChangeWrap', 'amountWrap', 'underPaidWrap',
    'underRequestWrap', 'overWrap', 'overRequestWrap', 'depositFeatures', 'payoutAmountWrap',
    'payoutFeeAmountWrap', 'payoutHint', 'walletSettings', 'nativeMethodWrap', 'usdOverWrap',
    'usdUnderWrap', 'usdOverRequestWrap', 'usdUnderRequestWrap', 'comBox', 'qrSettings',
    'regionInfo', 'cardNetworkWrap', 'googleMethodModeWrap', 'googleMethodHint',
    'returnToCashierWrap', 'h2hNotice']) {
    makeElement(id, '');
  }
  return root;
}

export function set(name, value) {
  const el = elements.get(name);
  if (!el) throw new Error(`Unknown control: ${name}`);
  if (el.type === 'checkbox') el.checked = !!value;
  else el.value = value;
}

export function get(name) {
  return elements.get(name);
}

export { root };
