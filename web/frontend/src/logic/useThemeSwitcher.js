import { useState, useEffect, useCallback } from 'react';
import Storage from '../utils/Storage';
import { THEME_MANIFESTS } from '../themes/manifests';
import { normalizeThemeId } from '../registry/theme';

export const THEME_MODES = [
    { value: 'light', label: 'Light' },
    { value: 'dark', label: 'Dark' },
    { value: 'system', label: 'System' },
    { value: 'time', label: 'Auto' },
];

const VALID_MODES = THEME_MODES.map((m) => m.value);

/**
 * Shared theme/mode switching behavior so every theme's TopBar (and the
 * guest menu) can expose the same controls without duplicating the storage
 * keys + event wiring. Visuals stay per-theme; only behavior lives here.
 *
 * Reads/writes the same `theme_id` / `theme_mode` localStorage keys and
 * `themeIdChanged` / `themeModeChanged` window events that App.js listens to.
 */
export default function useThemeSwitcher() {
    const [themeId, setThemeIdState] = useState(() => {
        try {
            return normalizeThemeId(Storage.load('theme_id', 'default'));
        } catch (_) {
            return 'default';
        }
    });
    const [themeMode, setThemeModeState] = useState(() => {
        try {
            const v = Storage.load('theme_mode', 'system');
            return VALID_MODES.includes(v) ? v : 'system';
        } catch (_) {
            return 'system';
        }
    });

    useEffect(() => {
        const onThemeIdChanged = (e) => {
            const next = e?.detail?.themeId;
            if (next) setThemeIdState(normalizeThemeId(next));
        };
        const onThemeModeChanged = (e) => {
            const next = e?.detail?.mode;
            if (next) setThemeModeState(next);
        };
        window.addEventListener('themeIdChanged', onThemeIdChanged);
        window.addEventListener('themeModeChanged', onThemeModeChanged);
        return () => {
            window.removeEventListener('themeIdChanged', onThemeIdChanged);
            window.removeEventListener('themeModeChanged', onThemeModeChanged);
        };
    }, []);

    const pickTheme = useCallback((id) => {
        const normalized = normalizeThemeId(id);
        console.debug('[useThemeSwitcher] pickTheme', normalized);
        setThemeIdState(normalized);
        Storage.save('theme_id', normalized);
        try {
            window.dispatchEvent(new CustomEvent('themeIdChanged', { detail: { themeId: normalized } }));
        } catch (_) { }
    }, []);

    const pickMode = useCallback((mode) => {
        if (!VALID_MODES.includes(mode)) return;
        console.debug('[useThemeSwitcher] pickMode', mode);
        setThemeModeState(mode);
        Storage.save('theme_mode', mode);
        try {
            window.dispatchEvent(new CustomEvent('themeModeChanged', { detail: { mode } }));
        } catch (_) { }
    }, []);

    return {
        themeId,
        themeMode,
        themes: THEME_MANIFESTS,
        modes: THEME_MODES,
        pickTheme,
        pickMode,
    };
}
