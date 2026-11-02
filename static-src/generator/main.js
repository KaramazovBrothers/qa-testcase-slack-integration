// Browser entry point for the test-case generator.
// Loaded as an ES module; shares behaviour with the legacy inline script but
// keeps state in `store.js` instead of a closure.
import { state } from './generator/store.js';
import { installWorkspaceApi, start } from './generator/index.js';
import { bindEvents } from './generator/ui/events.js';
import { cacheStaticNodes } from './generator/ui/language.js';

const root = document.currentScript?.closest('[data-generator]')
  || Array.from(document.querySelectorAll('[data-generator]')).find((el) => el.dataset.ready !== '1');

if (root && root.dataset.ready !== '1') {
  state.root = root;
  state.accountRegion = root.querySelector('[data-id="region"]').value;
  // `start` needs the static-node cache before the first refresh; the cache
  // itself only walks the DOM, so it is safe to build it here.
  cacheStaticNodes();
  bindEvents();
  installWorkspaceApi();
  start(root);
}
