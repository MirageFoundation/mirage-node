/**
 * Pre-React: set `data-theme-id` on `<html>` from Storage (same rules as App).
 * Lets `public/index.html` target `html[data-theme-id="…"]` on first paint.
 *
 * @see ./theme.js
 */
import Storage from '../utils/Storage';
import { normalizeThemeId, DEFAULT_THEME_ID } from './theme';

const raw = Storage.load('theme_id', DEFAULT_THEME_ID);
const id = normalizeThemeId(raw);
if (id !== raw) Storage.save('theme_id', id);
try {
    document.documentElement.setAttribute('data-theme-id', id);
} catch (_) { /* ignore */ }
