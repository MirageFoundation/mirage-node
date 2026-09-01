import { useState, useEffect, useCallback, useRef } from "react";
import styled from "styled-components";
import { useLocation } from "react-router-dom";
import Storage from "../utils/Storage";
import seedVault from "../utils/SeedVault";
import { deleteUser } from "../utils/tx";
import usePendingDeletes from "./usePendingDeletes.js";
import { formatError } from "../utils/errorMessages";
import { normalizeThemeId, DEFAULT_THEME_ID } from "../registry/theme";

// How recently the vault must have been unlocked for a reveal to skip the
// step-up. Long enough to cover "unlock, then go back up my phrase", short
// enough that a walked-away session does not stay revealable.
const SEED_REVEAL_FRESH_MS = 120_000;
export const CheckboxInput = styled.input.attrs({
    type: 'checkbox'
})`
    appearance: none;
    -webkit-appearance: none;
    width: 0.75rem;
    height: 0.75rem;
    flex: 0 0 0.75rem;
    margin: 0;
    margin-top: 0.18rem;
    border-radius: ${({
    theme
}) => theme.layout.inputRadius};
    border: 1px solid ${({
    theme
}) => theme.colors.border};
    background: ${({
    theme
}) => theme.colors.panelAlt};
    box-sizing: border-box;
    display: inline-block;
    position: relative;
    cursor: pointer;
    transition: background-color 0.12s ease, border-color 0.12s ease;

    &:hover {
        border-color: ${({
    theme
}) => theme.colors.borderStrong};
    }

    &:focus {
        outline: none;
        box-shadow: ${({
    theme
}) => theme.layout.focusRing};
    }

    &:checked {
        background: #3b82f6;
        border-color: #3b82f6;
    }

    &:checked::after {
        content: '';
        width: 0.32em;
        height: 0.58em;
        border: solid #fff;
        border-width: 0 0.18em 0.18em 0;
        position: absolute;
        left: 50%;
        top: 50%;
        transform: translate(-50%, -58%) rotate(45deg);
    }

    &:disabled {
        opacity: 0.5;
        cursor: not-allowed;
    }
`;
export const RadioInput = styled.input.attrs({
    type: 'radio'
})`
    appearance: none;
    -webkit-appearance: none;
    width: 0.8rem;
    height: 0.8rem;
    flex: 0 0 0.8rem;
    margin: 0;
    margin-top: 0.15rem;
    border-radius: 50%;
    border: 1px solid ${({
    theme
}) => theme.colors.border};
    background: ${({
    theme
}) => theme.colors.panelAlt};
    box-sizing: border-box;
    display: inline-block;
    position: relative;
    cursor: pointer;
    transition: background-color 0.12s ease, border-color 0.12s ease;

    &:checked {
        border-color: #3b82f6;
        background: #3b82f6;
    }

    &:checked::after {
        content: '';
        width: 0.3rem;
        height: 0.3rem;
        background: #fff;
        border-radius: 50%;
        position: absolute;
        left: 50%;
        top: 50%;
        transform: translate(-50%, -50%);
    }

    &:disabled {
        opacity: 0.5;
        cursor: not-allowed;
    }
`;
export function useSettings({
    state
}) {
    const location = useLocation();
    const {
        getInfo: getDeleteInfo,
        formatStatus: formatDeleteStatus
    } = usePendingDeletes();
    const [themeId, setThemeId] = useState(() => {
        try {
            const raw = Storage.load('theme_id', DEFAULT_THEME_ID);
            const id = normalizeThemeId(raw);
            if (id !== raw) Storage.save('theme_id', id);
            return id;
        } catch (_) {
            return DEFAULT_THEME_ID;
        }
    });
    const [themeMode, setThemeMode] = useState(() => {
        try {
            return Storage.load('theme_mode', 'system');
        } catch (_) {
            return 'system';
        }
    });
    const [collapseThreshold, setCollapseThreshold] = useState(() => {
        try {
            const v = Storage.load('comment_auto_collapse_threshold', -5);
            const n = Number(v);
            return Number.isFinite(n) ? n : -5;
        } catch (_) {
            return -5;
        }
    });
    const [sidebarCommunitiesLimit, setSidebarCommunitiesLimit] = useState(() => {
        try {
            const v = Storage.load('sidebar_communities_limit', 10);
            const n = Number(v);
            return Number.isFinite(n) ? n : 10;
        } catch (_) {
            return 10;
        }
    });
    const [sidebarPeopleLimit, setSidebarPeopleLimit] = useState(() => {
        try {
            const v = Storage.load('sidebar_users_limit', 10);
            const n = Number(v);
            return Number.isFinite(n) ? n : 10;
        } catch (_) {
            return 10;
        }
    });
    const [hideDownvotedPosts, setHideDownvotedPosts] = useState(() => {
        try {
            const val = Storage.load('hide_downvoted_posts', false);
            return val === true ? true : false;
        } catch (_) {
            return false;
        }
    });
    const [blurSensitiveMedia, setBlurSensitiveMedia] = useState(() => {
        try {
            const val = Storage.load('blur_sensitive_media', true);
            return val === false ? false : true;
        } catch (_) {
            return true;
        }
    });
    const [autoplayMedia, setAutoplayMedia] = useState(() => {
        try {
            return Storage.load('autoplay_media', false) === true;
        } catch (_) {
            return false;
        }
    });
    // Content tag visibility (default: only sensitive shown, others hidden)
    const [showTagSensitive, setShowTagSensitive] = useState(() => {
        try {
            const val = Storage.load('show_tag_sensitive', true);
            return val === false ? false : true;
        } catch (_) {
            return true;
        }
    });
    const [showTagAdult, setShowTagAdult] = useState(() => {
        try {
            if (typeof window !== 'undefined' && window.localStorage) {
                const adultRaw = window.localStorage.getItem('show_tag_adult');
                if (adultRaw !== null) return JSON.parse(adultRaw) === true;
                // TODO: remove show_tag_porn alias once app update is fully rolled out
                const legacyRaw = window.localStorage.getItem('show_tag_porn');
                if (legacyRaw !== null) return JSON.parse(legacyRaw) === true;
            }
            return false;
        } catch (_) {
            return false;
        }
    });
    const [showTagViolence, setShowTagViolence] = useState(() => {
        try {
            return Storage.load('show_tag_violence', false) === true;
        } catch (_) {
            return false;
        }
    });
    const [showTagGore, setShowTagGore] = useState(() => {
        try {
            return Storage.load('show_tag_gore', false) === true;
        } catch (_) {
            return false;
        }
    });
    const [showTagDeath, setShowTagDeath] = useState(() => {
        try {
            return Storage.load('show_tag_death', false) === true;
        } catch (_) {
            return false;
        }
    });

    // ── Security: seed storage mode ────────────────────────────────────────
    const [seedMode, setSeedMode] = useState(() => seedVault.getMode());
    const [prfSupported] = useState(() => seedVault.isPRFSupported());
    const [secPassword, setSecPassword] = useState('');
    const [secPasswordConfirm, setSecPasswordConfirm] = useState('');
    const [secPending, setSecPending] = useState(null); // mode being switched to (shows inline UI)
    const [secError, setSecError] = useState('');
    const [secSuccess, setSecSuccess] = useState('');
    const [secBusy, setSecBusy] = useState(false);
    const secSuccessTimeoutRef = useRef(null);
    const [deleteConfirmText, setDeleteConfirmText] = useState('');
    const [deleteError, setDeleteError] = useState('');
    const [deleteSuccess, setDeleteSuccess] = useState('');
    const [deleteSubmitting, setDeleteSubmitting] = useState(false);
    const deleteTarget = String(state?.publicKey || '').trim().toLowerCase();
    const deleteInfo = getDeleteInfo(deleteTarget);
    const deleteStatus = formatDeleteStatus(deleteTarget);
    const deleteBusy = deleteSubmitting || !!deleteInfo;
    const deleteConfirmReady = deleteConfirmText.trim().toUpperCase() === 'DELETE';
    const [seedRevealed, setSeedRevealed] = useState(false);
    const [seedCopied, setSeedCopied] = useState(false);
    const [vaultAutoLockMinutes, setVaultAutoLockMinutesState] = useState(() => {
        try {
            return seedVault.getAutoLockMinutes();
        } catch (_) {
            return 15;
        }
    });
    const setVaultAutoLockMinutes = useCallback((mins) => {
        seedVault.setAutoLockMinutes(mins);
        setVaultAutoLockMinutesState(seedVault.getAutoLockMinutes());
        try {
            console.debug('[Settings] vault-auto-lock', { minutes: mins });
        } catch (_) { /* noop */ }
    }, []);

    // Auto-hide seed after 60 seconds
    useEffect(() => {
        if (!seedRevealed) return;
        const timer = setTimeout(() => setSeedRevealed(false), 60_000);
        return () => clearTimeout(timer);
    }, [seedRevealed]);

    // ── Security: step-up before revealing the recovery phrase ─────────────
    // Limiting how long the phrase is exposed is the entire point of a protected
    // vault, so revealing it from an already-unlocked session has to cost the
    // secret again. Plaintext and memory modes have nothing to challenge with:
    // the phrase is readable from localStorage (or is only in RAM) regardless.
    const [seedRevealPrompt, setSeedRevealPrompt] = useState(null); // null | 'password'
    const [seedRevealPassword, setSeedRevealPassword] = useState('');
    const [seedRevealBusy, setSeedRevealBusy] = useState(false);
    const cancelSeedReveal = useCallback(() => {
        setSeedRevealPrompt(null);
        setSeedRevealPassword('');
    }, []);
    const requestSeedReveal = useCallback(async () => {
        setSecError('');
        if (!seedVault.getSeed()) {
            setSecError('No seed phrase available. Please sign in first.');
            return;
        }
        const mode = seedVault.getMode();
        const protectedMode = mode === 'password' || mode === 'passkey';
        if (!protectedMode || seedVault.requireFreshUnlock(SEED_REVEAL_FRESH_MS)) {
            setSeedRevealed(true);
            setSeedCopied(false);
            return;
        }
        if (mode === 'password') {
            setSeedRevealPassword('');
            setSeedRevealPrompt('password');
            return;
        }
        // Passkey re-authentication is its own prompt — no field to render.
        setSeedRevealBusy(true);
        try {
            await seedVault.unlock(null);
            setSeedRevealed(true);
            setSeedCopied(false);
        } catch (e) {
            setSecError(String(e?.message || 'Passkey verification failed'));
        } finally {
            setSeedRevealBusy(false);
        }
    }, []);
    const confirmSeedReveal = useCallback(async () => {
        setSecError('');
        setSeedRevealBusy(true);
        try {
            await seedVault.unlock(seedRevealPassword);
            setSeedRevealPrompt(null);
            setSeedRevealPassword('');
            setSeedRevealed(true);
            setSeedCopied(false);
        } catch (e) {
            setSecError(String(e?.message || 'Incorrect password'));
        } finally {
            setSeedRevealBusy(false);
        }
    }, [seedRevealPassword]);
    useEffect(() => () => {
        if (secSuccessTimeoutRef.current) {
            clearTimeout(secSuccessTimeoutRef.current);
            secSuccessTimeoutRef.current = null;
        }
    }, []);
    const commitModeSwitch = useCallback(async (newMode, password) => {
        setSecBusy(true);
        setSecError('');
        setSecSuccess('');
        try {
            const seed = seedVault.getSeed();
            if (!seed) {
                setSecError('No seed phrase in memory. Please sign in first.');
                setSecBusy(false);
                return;
            }
            if (newMode === 'password') {
                if (!password || password.length < 12) {
                    setSecError('Password must be at least 12 characters.');
                    setSecBusy(false);
                    return;
                }
                if (password !== secPasswordConfirm) {
                    setSecError('Passwords do not match.');
                    setSecBusy(false);
                    return;
                }
                // Reject trivially weak patterns locally (never log the password).
                const lower = password.toLowerCase();
                const weak = ['password', 'password123', '123456789012', 'qwertyuiopas', 'miragepassword'];
                if (weak.some((w) => lower.includes(w)) || /^(.)\1+$/.test(password)) {
                    setSecError('Choose a stronger password.');
                    setSecBusy(false);
                    return;
                }
                await seedVault.storeSeed(seed, 'password', password);
            } else if (newMode === 'passkey') {
                await seedVault.registerPasskey(seed);
            } else if (newMode === 'memory') {
                await seedVault.storeSeed(seed, 'memory', null);
            } else {
                await seedVault.storeSeed(seed, 'insecure', null);
            }
            // Re-persist publicKey and username to localStorage — they may have been
            // cleared by the memory-mode redirect in another tab (localStorage is shared).
            if (state.publicKey) Storage.save('publicKey', state.publicKey);
            if (state.username) Storage.save('username', state.username);
            setSeedMode(newMode);
            setSecPending(null);
            setSecPassword('');
            setSecPasswordConfirm('');
            const modeLabels = {
                insecure: 'Unencrypted',
                password: 'Password',
                memory: 'Memory-only',
                passkey: 'Passkey'
            };
            setSecSuccess(`${modeLabels[newMode] || 'Storage'} storage updated.`);
            if (secSuccessTimeoutRef.current) clearTimeout(secSuccessTimeoutRef.current);
            secSuccessTimeoutRef.current = setTimeout(() => {
                setSecSuccess('');
                secSuccessTimeoutRef.current = null;
            }, 5000);
        } catch (e) {
            const msg = String(e?.message || e || '');
            // Don't show raw browser WebAuthn errors (e.g. "FallbackRequested",
            // "The operation either timed out or was not allowed") — just reset.
            if (newMode === 'passkey' && /cancel|abort|not.allowed|timeout|fallback/i.test(msg)) {
                setSecPending(null);
            } else {
                setSecError(msg || 'Failed to switch mode');
            }
        } finally {
            setSecBusy(false);
        }
    }, [state.publicKey, state.username]);
    const handleModeSelect = useCallback(newMode => {
        setSecError('');
        setSecSuccess('');
        if (newMode === seedMode) {
            setSecPending(null);
            return;
        }
        if (newMode === 'password') {
            setSecPending('password');
            setSecPassword('');
            setSecPasswordConfirm('');
        } else if (newMode === 'passkey') {
            // Directly trigger passkey enrollment
            setSecPending('passkey');
            commitModeSwitch('passkey', null);
        } else {
            // insecure or memory — switch immediately
            setSecPending(null);
            commitModeSwitch(newMode, null);
        }
    }, [seedMode, commitModeSwitch]);

    const handleThemeIdChange = e => {
        const newId = normalizeThemeId(e.target.value);
        setThemeId(newId);
        Storage.save('theme_id', newId);
        window.dispatchEvent(new CustomEvent('themeIdChanged', {
            detail: {
                themeId: newId
            }
        }));
    };
    const handleThemeModeChange = e => {
        const newMode = e.target.value;
        setThemeMode(newMode);
        Storage.save('theme_mode', newMode);
        window.dispatchEvent(new CustomEvent('themeModeChanged', {
            detail: {
                mode: newMode
            }
        }));
    };
    const handleCollapseThresholdChange = e => {
        const raw = e.target.value;
        if (raw === '' || raw === '-' || raw === '−') {
            setCollapseThreshold(NaN);
            return;
        }
        const n = Number(raw);
        if (!Number.isFinite(n)) return;
        setCollapseThreshold(n);
        Storage.save('comment_auto_collapse_threshold', n);
    };
    const handleSidebarCommunitiesLimitChange = e => {
        const n = Number(e.target.value);
        if (!Number.isFinite(n)) return;
        setSidebarCommunitiesLimit(n);
        Storage.save('sidebar_communities_limit', n);
        window.dispatchEvent(new CustomEvent('sidebarSettingsUpdated'));
    };
    const handleSidebarPeopleLimitChange = e => {
        const n = Number(e.target.value);
        if (!Number.isFinite(n)) return;
        setSidebarPeopleLimit(n);
        Storage.save('sidebar_users_limit', n);
        window.dispatchEvent(new CustomEvent('sidebarSettingsUpdated'));
    };
    const getThemeExplanation = mode => {
        switch (mode) {
            case 'dark':
                return 'Always use dark theme';
            case 'light':
                return 'Always use light theme';
            case 'system':
                return 'Follows system theme preference';
            case 'time':
                return 'Light theme during daytime hours, dark theme at night (based on date & time)';
            default:
                return '';
        }
    };
    const handleDeleteAccount = async () => {
        setDeleteError('');
        setDeleteSuccess('');
        if (!deleteTarget || deleteTarget === 'guest') {
            setDeleteError('Not signed in.');
            return;
        }
        if (!deleteTarget.startsWith('mirage1')) {
            setDeleteError('Invalid account address.');
            return;
        }
        if (!deleteConfirmReady) {
            setDeleteError('Type DELETE to confirm.');
            return;
        }
        if (deleteBusy) {
            return;
        }
        setDeleteSubmitting(true);
        console.debug('[Settings] delete_user.start', {
            target: deleteTarget
        });
        try {
            const result = await deleteUser();
            console.debug('[Settings] delete_user.result', result);
            if (result && result.success) {
                if (!result.tx_hash) {
                    setDeleteError('Delete account failed: missing tx hash.');
                    setDeleteSubmitting(false);
                    return;
                }
                seedVault.clear();
                Storage.clear();
                window.location.replace('/');
                return;
            } else {
                setDeleteError(formatError(result));
            }
        } catch (err) {
            setDeleteError(String(err?.message || err || 'Delete account failed.'));
        } finally {
            setDeleteSubmitting(false);
        }
    };
    return {
        location,
        themeId,
        themeMode,
        collapseThreshold,
        sidebarCommunitiesLimit,
        sidebarPeopleLimit,
        hideDownvotedPosts,
        setHideDownvotedPosts,
        blurSensitiveMedia,
        setBlurSensitiveMedia,
        autoplayMedia,
        setAutoplayMedia,
        showTagSensitive,
        setShowTagSensitive,
        showTagAdult,
        setShowTagAdult,
        showTagViolence,
        setShowTagViolence,
        showTagGore,
        setShowTagGore,
        showTagDeath,
        setShowTagDeath,
        seedMode,
        prfSupported,
        secPassword,
        setSecPassword,
        secPasswordConfirm,
        setSecPasswordConfirm,
        secPending,
        secError,
        setSecError,
        secSuccess,
        secBusy,
        deleteConfirmText,
        setDeleteConfirmText,
        deleteError,
        setDeleteError,
        deleteSuccess,
        setDeleteSuccess,
        deleteStatus,
        deleteBusy,
        deleteConfirmReady,
        seedRevealed,
        setSeedRevealed,
        seedCopied,
        setSeedCopied,
        seedRevealPrompt,
        seedRevealPassword,
        setSeedRevealPassword,
        seedRevealBusy,
        requestSeedReveal,
        confirmSeedReveal,
        cancelSeedReveal,
        vaultAutoLockMinutes,
        setVaultAutoLockMinutes,
        commitModeSwitch,
        handleModeSelect,
        handleThemeIdChange,
        handleThemeModeChange,
        handleCollapseThresholdChange,
        handleSidebarCommunitiesLimitChange,
        handleSidebarPeopleLimitChange,
        getThemeExplanation,
        handleDeleteAccount
    };
}
