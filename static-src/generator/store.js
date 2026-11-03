// Single source of truth for generator state that outlives a render.
// Kept dependency-free so every module can import it without cycles.
export const state = {
  root: null,
  /** 'ru' | 'en' | 'uk' */
  language: 'ru',
  protectValues: false,
  /** @type {string[]} */
  protectedValues: [],
  payoutFeeManual: false,
  /** @type {Record<string, string[]> | null} */
  mentionDefaults: null,
  /** @type {Record<string, string[]>} */
  mentionEdits: {},
  /** Cached Slack member id -> display name, so a mention reads as a person. */
  /** @type {Record<string, string>} */
  slackPeople: {},
  generated: false,
  /** @type {Record<string, unknown> | null} */
  workspaceHooks: null,
  /** @type {Array<Record<string, unknown>>} */
  accountOptions: [],
  accountRegion: '',
  accountRequest: 0,
};

/** Resolve a `[data-id]` element inside the generator root. */
export const $ = (id) => state.root && state.root.querySelector(`[data-id="${id}"]`);

/** Current value of an input, honouring the "protect placeholders" mode. */
export const val = (id, fallback = '') => {
  const el = $(id);
  const value = el && el.value.trim();
  if (state.protectValues && value) {
    const token = `⟦VALUE${state.protectedValues.length}⟧`;
    state.protectedValues.push(value);
    return token;
  }
  return value || fallback;
};

/** Checkbox state of an input. */
export const checked = (id) => !!($(id) && $(id).checked);

/**
 * Set the active language and keep the module-level alias in sync.
 * The generator is loaded before the workspace frame, so a plain
 * setter is enough — no reactive plumbing required.
 */
export function setLanguage(language) {
  state.language = language;
}
