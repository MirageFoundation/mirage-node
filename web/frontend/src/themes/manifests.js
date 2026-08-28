/**
 * Theme registry — single place to register theme families.
 *
 * To add a theme:
 * 1. Create src/themes/<id>/ with index.js (manifest), tokens, Style, Layout, Shell, routes, components, …
 * 2. Import the manifest here and append to THEME_MANIFESTS.
 * 3. If you rename a theme id and need to migrate old localStorage values, add an entry to LEGACY_THEME_IDS.
 *
 * Order: THEME_MANIFESTS[0] is the default when storage is missing or invalid.
 * Themes own all visuals; shared app code lives in logic/, utils/, lib API — not under themes/.
 * Required `components` keys for App-level facades: see REQUIRED_THEME_COMPONENT_KEYS in src/registry/theme.js.
 */

import defaultManifest from './default/index';

// Only `default` is registered. The other families stay on disk so they can
// be wired back later; shipping them means every visible-copy change has to
// land in four places at once.
export const THEME_MANIFESTS = [defaultManifest];

/** Map old persisted theme_id values → current manifest id (renames only). */
export const LEGACY_THEME_IDS = Object.freeze({
    moon: 'bluemoon',
    mirageapp: 'default',
});
