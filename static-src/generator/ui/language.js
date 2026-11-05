import { state } from '../store.js';
import { translate } from '../translations/translations.js';
import { updateUI } from '../cases/payout.js';

const SKIP_SELECTOR = [
  'script', 'style',
  '[data-id="output"]', '[data-id="message"]', '[data-id="regionInfo"]',
  '[data-id="mentionList"]', '[data-id="mentionStatus"]',
].join(',');

/** Text nodes translated in place when the language changes. */
const translatableNodes = [];
/** Image thumbnails whose alt text is translated too. */
const thumbnails = [];

/** Collect the static DOM that `refreshLanguage` rewrites. Call once on start. */
export function cacheStaticNodes() {
  const root = state.root;
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  while (walker.nextNode()) {
    const node = walker.currentNode;
    if (node.parentElement.closest(SKIP_SELECTOR)) continue;
    if (node.nodeValue.trim()) translatableNodes.push([node, node.nodeValue]);
  }
  root.querySelectorAll('.thumbnail img').forEach((img) => thumbnails.push([img, img.alt]));
}

/** Re-apply the active language to the whole form. */
export function refreshLanguage() {
  const root = state.root;
  root.lang = state.language;
  translatableNodes.forEach(([node, original]) => {
    const core = original.trim();
    node.nodeValue = original.replace(core, translate(core));
  });
  thumbnails.forEach(([img, alt]) => { img.alt = translate(alt); });
  root.querySelectorAll('[data-lang]').forEach((button) => {
    button.setAttribute('aria-pressed', String(button.dataset.lang === state.language));
  });
  root.querySelector('.close-image').setAttribute('aria-label', translate('Закрыть изображение'));
  updateUI();
  root.querySelector('[data-id="regionInfo"]').innerHTML = translate(root.querySelector('[data-id="regionInfo"]').innerHTML);
}
