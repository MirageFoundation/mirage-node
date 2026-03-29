/**
 * Runs before React mount: set document data-theme-id from Storage using the same rules as the app.
 * Keeps theme id rules in one place (styled/theme.js + themes/manifests.js) — no duplicate logic in index.html.
 */
import Storage from './utils/Storage';
import { normalizeThemeId, DEFAULT_THEME_ID } from './styled/theme';

const raw = Storage.load('theme_id', DEFAULT_THEME_ID);
const id = normalizeThemeId(raw);
if (id !== raw) Storage.save('theme_id', id);
try {
    document.documentElement.setAttribute('data-theme-id', id);
} catch (_) { /* ignore */ }
