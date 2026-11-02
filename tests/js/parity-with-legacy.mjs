/**
 * Differential parity check: legacy generator vs refactored bundle.
 *
 * Loads the pre-refactor `generator.html` (inline IIFE) in jsdom, then loads
 * the built `app/static/generator.js` on the same markup, drives both with
 * identical form values and compares the produced case titles and texts.
 *
 * Run: node tests/js/parity-with-legacy.mjs <path-to-legacy-generator.html>
 */
import { readFileSync } from 'node:fs';
import { pathToFileURL } from 'node:url';
import { JSDOM } from 'jsdom';

const [legacyPath] = process.argv.slice(2);
if (!legacyPath) {
  console.error('usage: node parity-with-legacy.mjs <legacy generator.html>');
  process.exit(2);
}

const NEW_PAGE = 'app/static/generator.html';
const NEW_BUNDLE = 'app/static/generator.js';

/** Build a jsdom window around one generator markup. */
function makeWindow(markup) {
  const dom = new JSDOM(markup, {
    url: 'http://127.0.0.1:8000/generator',
    runScripts: 'outside-only',
    pretendToBeVisual: true,
  });
  const { window } = dom;
  window.fetch = async (url) => ({
    ok: true,
    status: 200,
    json: async () => (String(url).includes('region-mentions')
      ? { TR: ['@testuser1'], KZ: ['@kz1'] }
      : []),
  });
  // jsdom exposes `crypto` as a getter-only property.
  if (!window.crypto?.randomUUID) {
    Object.defineProperty(window, 'crypto', {
      configurable: true,
      value: {
        ...window.crypto,
        randomUUID: () => 'uuid-' + Math.random().toString(16).slice(2),
      },
    });
  }
  return window;}

const SETTINGS = {
  site: 'https://pinco.win/',
  method: 'TEST_METHOD_123',
  nativeMethod: 'NATIVE_METHOD_9',
  account: 'ACC-77',
  login: 'qa@test.io',
  password: 'Pa55word',
  usdAccount: 'USD-ACC',
  usdLogin: 'usd@test.io',
  usdPassword: 'usd-pass',
  amount: '500',
  overRequest: '600',
  overPaid: '650',
  underRequest: '450',
  underPaid: '400',
  usdAmount: '50',
  usdOverRequest: '60',
  usdUnderRequest: '40',
  usdOverPaid: '70',
  usdUnderPaid: '30',
  payoutAmount: '1000',
  payoutFeeAmount: '1331',
};

function applySettings(window, overrides) {
  const doc = window.document;
  const root = doc.querySelector('[data-generator]');
  const { flags = {}, ...inputs } = overrides;
  for (const [id, value] of Object.entries({ ...SETTINGS, ...inputs })) {
    const el = root.querySelector(`[data-id="${id}"]`);
    if (!el) throw new Error('missing control ' + id);
    el.value = value;
    el.dispatchEvent(new window.Event('input', { bubbles: true }));
  }
  for (const [id, flag] of Object.entries(flags)) {
    const el = root.querySelector(`[data-id="${id}"]`);
    if (!el) throw new Error('missing checkbox ' + id);
    el.checked = !!flag;
    el.dispatchEvent(new window.Event('input', { bubbles: true }));
    el.dispatchEvent(new window.Event('change', { bubbles: true }));
  }
}

function select(window, id, value) {
  const el = window.document.querySelector(`[data-generator] [data-id="${id}"]`);
  if (!el) throw new Error('missing select ' + id);
  el.value = value;
  el.dispatchEvent(new window.Event('input', { bubbles: true }));
}

/** Read the rendered cards, exactly what an operator copies. */
function readCases(window) {
  return [...window.document.querySelectorAll('[data-generator] [data-id="output"] .case')]
    .map((card) => ({
      title: card.querySelector('h3').textContent,
      text: card.querySelector('pre').textContent,
      request: card.querySelector('.case-request')?.value ?? '',
    }));
}

async function runLegacy(overrides) {
  const markup = readFileSync(legacyPath, 'utf8');
  const window = makeWindow(markup);
  // The legacy page runs its own inline IIFE through jsdom's script runner.
  const inline = /<script>([\s\S]*?)<\/script>/.exec(markup);
  window.eval(inline[1].replace('document.currentScript', 'null'));
  await window.qaGenerator?.ready?.catch?.(() => {});
  applySettings(window, overrides);
  window.document.querySelector('[data-generator] [data-id="generate"]').click();
  return readCases(window);
}

async function runNew(overrides) {
  const markup = readFileSync(NEW_PAGE, 'utf8');
  const window = makeWindow(markup);
  const bundle = readFileSync(NEW_BUNDLE, 'utf8');
  // jsdom has no module loader; evaluate the already-bundled ES module body.
  window.eval(bundle.replace(/^\/\/.*$/gm, ''));
  await window.qaGenerator?.ready?.catch?.(() => {});
  applySettings(window, overrides);
  window.document.querySelector('[data-generator] [data-id="generate"]').click();
  return readCases(window);
}

const MATRIX = [
  { name: 'TR / pinco / HPP / default', overrides: {} },
  { name: 'TR / com / HPP', overrides: { license: 'com' } },
  { name: 'TR / zazino / HPP', overrides: { license: 'zazino' } },
  { name: 'KZ / pinco / HPP', overrides: { region: 'KZ' } },
  { name: 'RU / com / HPP', overrides: { region: 'RU', license: 'com' } },
  { name: 'TR / pinco / H2H', overrides: { integration: 'H2H' } },
  { name: 'TR / payout', overrides: { integration: 'payout' } },
  { name: 'TR / payout / com', overrides: { integration: 'payout', license: 'com' } },
  { name: 'Apple Pay', overrides: { wallet: 'apple' } },
  { name: 'Google Pay / both cards', overrides: { wallet: 'google', cardNetwork: 'both' } },
  { name: 'QR camera', overrides: { flags: { qr: true } } },
  { name: 'QR both scanners', overrides: { flags: { qr: true }, qrScanner: 'both' } },
  { name: 'receipt', overrides: { flags: { receipt: true } } },
  { name: 'oneClick', overrides: { flags: { oneClick: true } } },
  { name: 'cashier return', overrides: { flags: { returnToCashier: true } } },
  { name: 'amount change', overrides: { amountChange: 'yes' } },
  { name: 'timer + cancel', overrides: { flags: { timer: true, cancel: true } } },
  { name: 'all flags', overrides: {
    amountChange: 'yes',
    flags: { qr: true, receipt: true, oneClick: true, returnToCashier: true, timer: true, cancel: true },
  } },
];

// Full cartesian coverage: every region x licence x integration, each with the
// amount-change flag enabled (the branch that adds over/underpayment cases).
const REGION_CODES = ['TR', 'AZ', 'CL', 'CA', 'GT', 'KZ', 'BO', 'UZ', 'IN', 'KG',
  'BD', 'MX', 'EC', 'HN', 'TJ', 'NG', 'KE', 'CG', 'RU'];
const LICENCES = ['pinco', 'com', 'zazino'];
for (const region of REGION_CODES) {
  for (const license of LICENCES) {
    for (const integration of ['HPP', 'H2H', 'payout']) {
      MATRIX.push({
        name: `${region} / ${license} / ${integration} / change`,
        overrides: { region, license, integration, amountChange: 'yes' },
      });
    }
  }
}

let failures = 0;
let compared = 0;
for (const scenario of MATRIX) {
  let legacy;
  let modern;
  try {
    legacy = await runLegacy(scenario.overrides);
  } catch (error) {
    console.log(`SKIP ${scenario.name}: legacy failed (${error.message})`);
    continue;
  }
  try {
    modern = await runNew(scenario.overrides);
  } catch (error) {
    console.log(`FAIL ${scenario.name}: new generator threw ${error.message}`);
    failures += 1;
    continue;
  }
  compared += 1;
  if (legacy.length !== modern.length) {
    console.log(`FAIL ${scenario.name}: count ${legacy.length} -> ${modern.length}`);
    failures += 1;
    continue;
  }
  const diffs = [];
  for (let i = 0; i < legacy.length; i += 1) {
    if (legacy[i].title !== modern[i].title) diffs.push(`  #${i + 1} title\n  A: ${legacy[i].title}\n  B: ${modern[i].title}`);
    if (legacy[i].text !== modern[i].text) diffs.push(`  #${i + 1} text\n  A: ${legacy[i].text.slice(0, 300)}\n  B: ${modern[i].text.slice(0, 300)}`);
    if (legacy[i].request !== modern[i].request) diffs.push(`  #${i + 1} request differs`);
  }
  if (diffs.length) {
    console.log(`FAIL ${scenario.name}: ${diffs.length} difference(s)`);
    console.log(diffs.slice(0, 3).join('\n'));
    failures += 1;
  } else {
    console.log(`OK   ${scenario.name} (${legacy.length} cases)`);
  }
}

console.log(`\nCompared ${compared} scenarios, failures: ${failures}`);
process.exit(failures ? 1 : 0);
