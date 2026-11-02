/**
 * Runtime check that the refactor kept the whole generator feature set.
 *
 * Compares the live `window.qaGenerator` surface of the legacy page and the
 * built bundle, then exercises the workspace adapter on the new build.
 */
import { readFileSync } from 'node:fs';
import { JSDOM } from 'jsdom';

const legacyPath = process.argv[2];
const NEW_PAGE = 'app/static/generator.html';
const NEW_BUNDLE = 'app/static/generator.js';

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
    json: async () => (String(url).includes('region-mentions') ? { TR: ['@t1'] } : []),
  });
  if (!window.crypto?.randomUUID) {
    Object.defineProperty(window, 'crypto', {
      configurable: true,
      value: { ...window.crypto, randomUUID: () => 'uuid-test' },
    });
  }
  return window;
}

async function loadLegacy() {
  const markup = readFileSync(legacyPath, 'utf8');
  const window = makeWindow(markup);
  const inline = /<script>([\s\S]*?)<\/script>/.exec(markup);
  window.eval(inline[1].replace('document.currentScript', 'null'));
  await window.qaGenerator?.ready?.catch?.(() => {});
  return window;
}

async function loadNew() {
  const window = makeWindow(readFileSync(NEW_PAGE, 'utf8'));
  window.eval(readFileSync(NEW_BUNDLE, 'utf8'));
  await window.qaGenerator?.ready?.catch?.(() => {});
  return window;
}

const failures = [];
const check = (label, passed, detail = '') => {
  if (passed) console.log(`OK   ${label}`);
  else { console.log(`FAIL ${label} ${detail}`); failures.push(label); }
};

const legacy = await loadLegacy();
const modern = await loadNew();

// --- public API surface -----------------------------------------------------
const apiOld = Object.keys(legacy.qaGenerator).sort();
const apiNew = Object.keys(modern.qaGenerator).sort();
const missing = apiOld.filter((key) => !apiNew.includes(key));
check('API: no method lost', missing.length === 0, `missing: ${missing.join(', ')}`);
check('API: ready promise present', typeof modern.qaGenerator.ready?.then === 'function');

// --- form controls ----------------------------------------------------------
const idsOf = (win) => [...win.document.querySelectorAll('[data-generator] [data-id]')]
  .map((el) => el.dataset.id).sort();
const oldIds = idsOf(legacy);
const newIds = idsOf(modern);
check('DOM: all data-id controls preserved', JSON.stringify(oldIds) === JSON.stringify(newIds),
  `old ${oldIds.length} vs new ${newIds.length}`);

// --- buttons ----------------------------------------------------------------
const buttonsOf = (win) => [...win.document.querySelectorAll('[data-generator] button')]
  .map((b) => b.textContent.trim() || b.className).sort();
const oldButtons = buttonsOf(legacy);
const newButtons = buttonsOf(modern);
check('DOM: all buttons preserved', JSON.stringify(oldButtons) === JSON.stringify(newButtons),
  `old ${oldButtons.length} vs new ${newButtons.length}`);

// --- translations -----------------------------------------------------------
const labels = (win) => [...win.document.querySelectorAll('[data-generator] label')]
  .map((l) => l.firstChild?.textContent?.trim()).filter(Boolean).sort();
check('i18n: all labels translated identically', JSON.stringify(labels(legacy)) === JSON.stringify(labels(modern)));

// --- mentions ---------------------------------------------------------------
// Checked before `restore()` because restore legitimately clears local edits.
check('mentions: region defaults rendered',
  modern.document.querySelectorAll('[data-generator] [data-id="mentionList"] .mention-row').length === 1);

// --- workspace adapter round trip ------------------------------------------
const snapshot = modern.qaGenerator.snapshot();
check('adapter: snapshot has fields/language/mentions',
  !!snapshot.fields && typeof snapshot.language === 'string' && !!snapshot.mention_edits);

modern.document.querySelector('[data-generator] [data-id="method"]').value = 'ROUND_TRIP';
const restored = { ...snapshot, fields: { ...snapshot.fields, method: 'RESTORED_1', region: 'KZ' } };
modern.qaGenerator.restore(restored);
const after = modern.qaGenerator.snapshot();
check('adapter: restore writes fields back', after.fields.method === 'RESTORED_1',
  `got ${after.fields.method}`);
check('adapter: restore resets generated output',
  modern.document.querySelector('[data-generator] [data-id="output"]').children.length === 0);

modern.qaGenerator.lockRegion(true);
check('adapter: lockRegion disables the select',
  modern.document.querySelector('[data-generator] [data-id="region"]').disabled === true);

// --- lightbox / dialog ------------------------------------------------------
check('DOM: lightbox dialog keeps its close button',
  !!modern.document.querySelector('[data-generator] dialog .close-image'));

// --- language switch --------------------------------------------------------
const enButton = [...modern.document.querySelectorAll('[data-generator] [data-lang]')].find((b) => b.dataset.lang === 'en');
enButton.click();
const englishSiteLabel = modern.document.querySelector('[data-generator] [data-id="site"]').closest('label').textContent.trim();
check('i18n: EN switch relabels the form', englishSiteLabel === 'Site URL', `got "${englishSiteLabel}"`);
const ruButton = [...modern.document.querySelectorAll('[data-generator] [data-lang]')].find((b) => b.dataset.lang === 'ru');
ruButton.click();
check('i18n: RU switch restores labels',
  modern.document.querySelector('[data-generator] [data-id="site"]').closest('label').textContent.trim().startsWith('Адрес сайта'));

console.log(`\nFeature checks failed: ${failures.length}`);
process.exit(failures.length ? 1 : 0);
