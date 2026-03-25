import React, { useState, useEffect, useCallback } from "react";
import { Helmet } from 'react-helmet-async';
import styled from "styled-components";
import { useLocation, Navigate } from 'react-router-dom';
import Storage from "../utils/Storage";
import seedVault from "../utils/SeedVault";
import { deleteUser } from "../utils/tx";
import Api from "../lib/api";
import { signPlainPayload } from "../utils/signPlain";
import usePendingDeletes from "../utils/usePendingDeletes";
import Sidebar from '../components/Sidebar';
import TopBar from '../components/TopBar';
import MobileHeader from '../components/MobileHeader';
import { ContentGrid, ModernPostFeed, TabbedContainer, ContainerTab, ContainerBody } from '../styled/Layout';

const Row = styled.div`
    display: grid;
    grid-template-columns: 14rem minmax(0, 1fr);
    gap: 0.5rem;
    align-items: start;
    margin: 0.4rem 0;
    @media (max-width: 1000px) {
        grid-template-columns: 1fr;
        gap: 0.35rem;
        align-items: stretch;
    }
`;

const Label = styled.div`
    color: ${({ theme }) => theme?.colors?.subtleText || '#ccc'};
    font-weight: 600;
    font-size: 0.85rem;
    white-space: nowrap;
    padding-top: 0.7rem;
    @media (max-width: 1000px) {
        padding-top: 0;
        margin-bottom: 0.1rem;
    }
`;

const ValueBox = styled.div`
    background-color: ${({ theme }) => theme?.colors?.panelAlt || '#1f2328'};
    border: 1px solid ${({ theme }) => theme?.colors?.border || '#444'};
    border-radius: 8px;
    padding: 0.75rem 1rem;
    width: 100%;
    box-sizing: border-box;
    overflow-x: auto;
`;

const ThemeSelect = styled.select`
    background-color: ${({ theme }) => theme?.colors?.panelAlt || '#1f2328'};
    border: 1px solid ${({ theme }) => theme?.colors?.border || '#444'};
    border-radius: 8px;
    padding: 0.5rem 0.85rem;
    color: ${({ theme }) => theme?.colors?.text || '#eee'};
    font-size: 0.85rem;
    width: 100%;
    cursor: pointer;
    transition: all 0.2s ease;
    
    &:focus {
        outline: none;
        border-color: #667eea;
        box-shadow: 0 0 0 3px rgba(102, 126, 234, 0.15);
    }
`;

const ExplanationText = styled.div`
    color: ${({ theme }) => theme?.colors?.subtleText || '#888'};
    font-size: 0.7rem;
    margin-top: 0.25rem;
    font-style: italic;
    line-height: 1.4;
`;

const CheckboxLabel = styled.label`
    /* Inline (shrink-to-content) so empty space to the right isn't clickable */
    display: inline-grid;
    grid-template-columns: auto minmax(0, 1fr);
    column-gap: 0.5rem;
    align-items: flex-start;
    color: ${({ theme }) => theme?.colors?.subtleText || '#888'};
    font-size: 0.85rem;
    line-height: 1.25;
    white-space: normal;
    max-width: 100%;
    cursor: pointer;
    user-select: none;

    /* Hover affordance: only highlight the checkbox itself (not the whole row) */
    &:hover input[type="checkbox"] {
        border-color: ${({ theme }) => theme?.colors?.borderStrong || theme?.colors?.border || 'rgba(255,255,255,0.28)'};
        box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.12);
    }
`;

const CheckboxInput = styled.input.attrs({ type: 'checkbox' })`
    /* Use a custom checkbox so alignment doesn't shift at different browser zoom levels */
    appearance: none;
    -webkit-appearance: none;
    width: 0.75rem;
    height: 0.75rem;
    flex: 0 0 0.75rem;
    margin: 0; /* avoid browser default checkbox margins that cause misalignment */
    /* Align with the first line of text (line-height is 1.25) */
    margin-top: 0.18rem;
    border-radius: 0.25rem;
    border: 1px solid ${({ theme }) => theme?.colors?.border || 'rgba(255,255,255,0.18)'};
    background: ${({ theme }) => theme?.colors?.panelAlt || '#1f2328'};
    box-sizing: border-box;
    display: inline-block;
    position: relative;
    cursor: pointer;
    transition: background-color 0.12s ease, border-color 0.12s ease;

    &:hover {
        border-color: ${({ theme }) => theme?.colors?.borderStrong || theme?.colors?.border || 'rgba(255,255,255,0.28)'};
    }

    &:focus {
        outline: none;
        box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.25);
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

const HelperText = styled.span`
    color: ${({ theme }) => theme?.colors?.subtleText || '#888'};
    font-size: 0.75rem;
`;

const SecurityBanner = styled.div`
    background-color: rgba(245, 158, 11, 0.1);
    border: 1px solid #f59e0b;
    border-radius: 6px;
    padding: 0.75rem;
    margin-bottom: 0.75rem;
    font-size: 0.78rem;
    line-height: 1.4;
    color: ${({ theme }) => theme?.colors?.text || '#eee'};
`;

const RadioGroup = styled.div`
    display: flex;
    flex-direction: column;
    gap: 0.6rem;
`;

const RadioLabel = styled.label`
    display: inline-grid;
    grid-template-columns: auto minmax(0, 1fr);
    column-gap: 0.5rem;
    align-items: flex-start;
    color: ${({ theme }) => theme?.colors?.subtleText || '#888'};
    font-size: 0.85rem;
    line-height: 1.25;
    cursor: ${({ $disabled }) => $disabled ? 'not-allowed' : 'pointer'};
    opacity: ${({ $disabled }) => $disabled ? 0.45 : 1};
    user-select: none;
`;

const RadioInput = styled.input.attrs({ type: 'radio' })`
    appearance: none;
    -webkit-appearance: none;
    width: 0.8rem;
    height: 0.8rem;
    flex: 0 0 0.8rem;
    margin: 0;
    margin-top: 0.15rem;
    border-radius: 50%;
    border: 1px solid ${({ theme }) => theme?.colors?.border || 'rgba(255,255,255,0.18)'};
    background: ${({ theme }) => theme?.colors?.panelAlt || '#1f2328'};
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

const RadioDescription = styled.span`
    display: block;
    font-size: 0.7rem;
    color: ${({ theme }) => theme?.colors?.subtleText || '#777'};
    font-style: italic;
    margin-top: 0.1rem;
`;

const InlinePasswordRow = styled.div`
    display: flex;
    gap: 0.5rem;
    align-items: center;
    margin-top: 0.5rem;
    flex-wrap: wrap;
`;

const PasswordInput = styled.input`
    flex: 1;
    min-width: 120px;
    max-width: 220px;
    padding: 0.45rem 0.7rem;
    font-size: 0.8rem;
    background-color: ${({ theme }) => theme?.colors?.panelAlt || '#1f2328'};
    border: 1px solid ${({ theme }) => theme?.colors?.border || '#444'};
    border-radius: 6px;
    color: ${({ theme }) => theme?.colors?.text || '#eee'};
    box-sizing: border-box;

    &:focus {
        outline: none;
        border-color: #667eea;
        box-shadow: 0 0 0 3px rgba(102, 126, 234, 0.15);
    }
`;

const SmallButton = styled.button`
    padding: 0.45rem 0.85rem;
    font-size: 0.78rem;
    font-weight: 600;
    cursor: pointer;
    border: none;
    border-radius: 6px;
    background: #3b82f6;
    color: #fff;
    transition: background 0.15s ease;
    white-space: nowrap;

    &:hover:not(:disabled) {
        background: #2563eb;
    }

    &:disabled {
        opacity: 0.5;
        cursor: not-allowed;
    }
`;

const DangerButton = styled(SmallButton)`
    background: #dc2626;

    &:hover:not(:disabled) {
        background: #b91c1c;
    }
`;

const DangerInput = styled.input`
    flex: 1;
    min-width: 160px;
    padding: 0.45rem 0.7rem;
    font-size: 0.8rem;
    background-color: ${({ theme }) => theme?.colors?.panelAlt || '#1f2328'};
    border: 1px solid ${({ theme }) => theme?.colors?.border || '#444'};
    border-radius: 6px;
    color: ${({ theme }) => theme?.colors?.text || '#eee'};
    box-sizing: border-box;

    &:focus {
        outline: none;
        border-color: #ef4444;
        box-shadow: 0 0 0 3px rgba(239, 68, 68, 0.2);
    }
`;

const DangerRow = styled.div`
    display: flex;
    gap: 0.5rem;
    align-items: center;
    flex-wrap: wrap;
`;

const DangerNotice = styled.div`
    color: #fca5a5;
    font-size: 0.72rem;
    line-height: 1.4;
    margin-bottom: 0.5rem;
`;

const SecurityError = styled.div`
    color: #f66;
    font-size: 0.72rem;
    margin-top: 0.35rem;
`;

const SecuritySuccess = styled.div`
    background-color: rgba(34, 197, 94, 0.1);
    border: 1px solid #22c55e;
    border-radius: 3px;
    padding: 0.5rem 0.75rem;
    margin-top: 0.5rem;
    color: #22c55e;
    font-size: 0.78rem;
    display: flex;
    align-items: center;
    gap: 0.4rem;
`;

const SeedGrid = styled.div`
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 0.4rem;
    max-width: 100%;
    margin: 0.5rem 0;
    padding: 0.75rem;
    background-color: ${({ theme }) => theme?.colors?.panel || '#1a1e23'};
    border: 1px solid ${({ theme }) => theme?.colors?.border || '#444'};
    border-radius: 4px;
    position: relative;
    box-sizing: border-box;

    @media (max-width: 1000px) {
        grid-template-columns: repeat(3, 1fr);
        padding: 0.5rem;
        gap: 0.3rem;
    }
`;

const SeedWord = styled.div`
    background-color: ${({ theme }) => theme?.colors?.panelAlt || '#2a2e33'};
    border: 1px solid ${({ theme }) => theme?.colors?.border || '#555'};
    border-radius: 3px;
    padding: 0.3rem 0.2rem;
    text-align: left;
    font-size: 0.75rem;
    color: ${({ theme }) => theme?.colors?.text || '#e5e7eb'};
    font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
    display: flex;
    align-items: center;
    gap: 0.2rem;
    white-space: nowrap;
    word-break: normal;
    overflow-wrap: normal;

    &:before {
        content: attr(data-index);
        color: ${({ theme }) => theme?.colors?.subtleText || '#9ca3af'};
        font-size: 0.5rem;
        min-width: 12px;
        font-weight: bold;
    }

    @media (max-width: 400px) {
        font-size: 0.7rem;
        padding: 0.25rem 0.15rem;
        gap: 0.1rem;
        &:before {
            font-size: 0.45rem;
            min-width: 10px;
        }
    }
`;

const SeedWarning = styled.div`
    color: #f59e0b;
    font-size: 0.7rem;
    line-height: 1.35;
    margin-bottom: 0.5rem;
`;

const Divider = styled.hr`
    border: none;
    border-top: 1px solid ${({ theme }) => theme?.colors?.border || '#444'};
    margin: 0.75rem 0;
`;


export default function SettingsView({ state }) {
    const location = useLocation();
    const { getInfo: getDeleteInfo, formatStatus: formatDeleteStatus } = usePendingDeletes();

    const [themeMode, setThemeMode] = useState(() => {
        try {
            return Storage.load('theme_mode', 'time');
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
    const [sidebarTopicsLimit, setSidebarTopicsLimit] = useState(() => {
        try {
            const v = Storage.load('sidebar_topics_limit', 10);
            const n = Number(v);
            return Number.isFinite(n) ? n : 10;
        } catch (_) {
            return 10;
        }
    });
    const [sidebarPeopleLimit, setSidebarPeopleLimit] = useState(() => {
        try {
            const v = Storage.load('sidebar_people_limit', 10);
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
    // Content tag visibility (default: only sensitive shown, others hidden)
    const [showTagSensitive, setShowTagSensitive] = useState(() => {
        try {
            const val = Storage.load('show_tag_sensitive', true);
            return val === false ? false : true;
        } catch (_) {
            return true;
        }
    });
    const [showTagPorn, setShowTagPorn] = useState(() => {
        try {
            return Storage.load('show_tag_porn', false) === true;
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
    const [fullWidthMode, setFullWidthMode] = useState(() => {
        try {
            return Storage.load('full_width_mode', false) === true;
        } catch (_) {
            return false;
        }
    });
    const [referralPrecheckEnabled, setReferralPrecheckEnabled] = useState(() => {
        try {
            return Storage.load('referral_precheck_enabled', false) === true;
        } catch (_) {
            return false;
        }
    });
    const [referralPrecheckBusy, setReferralPrecheckBusy] = useState(false);
    const [referralPrecheckError, setReferralPrecheckError] = useState('');
    const [referralPrecheckSuccess, setReferralPrecheckSuccess] = useState('');

    // ── Security: seed storage mode ────────────────────────────────────────
    const [seedMode, setSeedMode] = useState(() => seedVault.getMode());
    const [prfSupported] = useState(() => seedVault.isPRFSupported());
    const [secPassword, setSecPassword] = useState('');
    const [secPasswordConfirm, setSecPasswordConfirm] = useState('');
    const [secPending, setSecPending] = useState(null);   // mode being switched to (shows inline UI)
    const [secError, setSecError] = useState('');
    const [secSuccess, setSecSuccess] = useState('');
    const [secBusy, setSecBusy] = useState(false);
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

    // Auto-hide seed after 60 seconds
    useEffect(() => {
        if (!seedRevealed) return;
        const timer = setTimeout(() => setSeedRevealed(false), 60_000);
        return () => clearTimeout(timer);
    }, [seedRevealed]);

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
                if (!password || password.length < 4) {
                    setSecError('Password must be at least 4 characters.');
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
            const modeLabels = { insecure: 'Unencrypted', password: 'Password', memory: 'Memory-only', passkey: 'Passkey' };
            setSecSuccess(`${modeLabels[newMode] || 'Storage'} storage updated.`);
            setTimeout(() => setSecSuccess(''), 5000);
        } catch (e) {
            const msg = String(e?.message || e || '');
            // Don't show raw browser WebAuthn errors (e.g. "FallbackRequested",
            // "The operation either timed out or was not allowed") — just reset.
            if (newMode === 'passkey' && (
                /cancel|abort|not.allowed|timeout|fallback/i.test(msg)
            )) {
                setSecPending(null);
            } else {
                setSecError(msg || 'Failed to switch mode');
            }
        } finally {
            setSecBusy(false);
        }
    }, [state.publicKey, state.username]);

    const handleModeSelect = useCallback((newMode) => {
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

    // Apply full width mode on mount and when it changes
    useEffect(() => {
        const root = document.documentElement;
        if (fullWidthMode) {
            root.style.setProperty('--content-max-width', 'none');
            root.style.setProperty('--feed-max-width', 'none');
        } else {
            root.style.setProperty('--content-max-width', '1240px');
            root.style.setProperty('--feed-max-width', '1000px');
        }
    }, [fullWidthMode]);

    useEffect(() => {
        if (!state.publicKey) return;
        let cancelled = false;
        Api.get('get_user_status', { address: state.publicKey, _cb: Date.now() })
            .then((data) => {
                if (cancelled || !data) return;
                if (typeof data.referral_precheck_enabled === 'boolean') {
                    setReferralPrecheckEnabled(data.referral_precheck_enabled);
                    Storage.save('referral_precheck_enabled', data.referral_precheck_enabled);
                }
            })
            .catch(() => { });
        return () => { cancelled = true; };
    }, [state.publicKey]);

    const handleThemeModeChange = (e) => {
        const newMode = e.target.value;
        setThemeMode(newMode);
        Storage.save('theme_mode', newMode);
        // Trigger a custom event that App.js can listen to
        window.dispatchEvent(new CustomEvent('themeModeChanged', { detail: { mode: newMode } }));
    };

    const handleReferralPrecheckToggle = async (nextVal) => {
        if (!state.publicKey || referralPrecheckBusy) return;
        setReferralPrecheckBusy(true);
        setReferralPrecheckError('');
        setReferralPrecheckSuccess('');
        try {
            const addr = state.publicKey.toLowerCase();
            const sig = await signPlainPayload((ts, n) => `referrals_precheck_opt_in:${addr}:${nextVal ? 1 : 0}:${ts}:${n}`);
            const res = await Api.post('referrals/precheck_opt_in', {
                address: state.publicKey,
                enabled: !!nextVal,
                ...sig,
            });
            if (!res || res.precheck_enabled !== !!nextVal) {
                throw new Error('Unexpected response');
            }
            setReferralPrecheckEnabled(!!nextVal);
            Storage.save('referral_precheck_enabled', !!nextVal);
            setReferralPrecheckSuccess('Saved.');
            setTimeout(() => setReferralPrecheckSuccess(''), 3000);
        } catch (e) {
            setReferralPrecheckError(String(e?.message || e || 'Failed to update'));
        } finally {
            setReferralPrecheckBusy(false);
        }
    };


    const handleCollapseThresholdChange = (e) => {
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

    const handleSidebarTopicsLimitChange = (e) => {
        const n = Number(e.target.value);
        if (!Number.isFinite(n)) return;
        setSidebarTopicsLimit(n);
        Storage.save('sidebar_topics_limit', n);
        window.dispatchEvent(new CustomEvent('sidebarSettingsUpdated'));
    };

    const handleSidebarPeopleLimitChange = (e) => {
        const n = Number(e.target.value);
        if (!Number.isFinite(n)) return;
        setSidebarPeopleLimit(n);
        Storage.save('sidebar_people_limit', n);
        window.dispatchEvent(new CustomEvent('sidebarSettingsUpdated'));
    };

    const getThemeExplanation = (mode) => {
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
        console.debug('[Settings] delete_user.start', { target: deleteTarget });
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
                setDeleteError(result?.error || 'Delete account failed.');
            }
        } catch (err) {
            setDeleteError(String(err?.message || err || 'Delete account failed.'));
        } finally {
            setDeleteSubmitting(false);
        }
    };

    if (!state.publicKey) {
        return <Navigate to="/login" replace />;
    }

    return (
        <ContentGrid>
            <Helmet>
                <title>Settings | Mirage</title>
            </Helmet>
            <Sidebar currentPath={location.pathname} state={state} />
            <div>
                <TopBar state={state} />
                <ModernPostFeed>
                    <MobileHeader />
                    <TabbedContainer>
                        <ContainerTab>Settings</ContainerTab>
                        <ContainerBody>
                            {/* ── Security rows (top of settings) ──────────── */}
                            {seedMode === 'insecure' && state.publicKey && (
                                <SecurityBanner>
                                    Your recovery phrase is stored unencrypted in this browser. Consider enabling password or passkey protection below.
                                </SecurityBanner>
                            )}

                            <Row>
                                <Label style={{ whiteSpace: 'normal' }}>Seed phrase storage:</Label>
                                <ValueBox>
                                    <RadioGroup>
                                        <RadioLabel>
                                            <RadioInput
                                                name="seed_mode"
                                                value="insecure"
                                                checked={seedMode === 'insecure' && secPending !== 'password'}
                                                onChange={() => handleModeSelect('insecure')}
                                                disabled={secBusy}
                                            />
                                            <span>
                                                Unencrypted (default)
                                                <RadioDescription>Fastest. Seed stored in plaintext in browser storage.</RadioDescription>
                                            </span>
                                        </RadioLabel>
                                        {secSuccess && seedMode === 'insecure' && <SecuritySuccess><span>✓</span>{secSuccess}</SecuritySuccess>}

                                        <RadioLabel>
                                            <RadioInput
                                                name="seed_mode"
                                                value="password"
                                                checked={seedMode === 'password' || secPending === 'password'}
                                                onChange={() => handleModeSelect('password')}
                                                disabled={secBusy}
                                            />
                                            <span>
                                                Password encrypted
                                                <RadioDescription>Seed encrypted with a password you choose. Enter it once per session to unlock.</RadioDescription>
                                            </span>
                                        </RadioLabel>

                                        {secPending === 'password' && (
                                            <div style={{ paddingLeft: '1.3rem' }}>
                                                <InlinePasswordRow>
                                                    <PasswordInput
                                                        type="password"
                                                        placeholder="Password"
                                                        value={secPassword}
                                                        onChange={(e) => { setSecPassword(e.target.value); setSecError(''); }}
                                                        disabled={secBusy}
                                                        autoFocus
                                                    />
                                                </InlinePasswordRow>
                                                <InlinePasswordRow>
                                                    <PasswordInput
                                                        type="password"
                                                        placeholder="Confirm password"
                                                        value={secPasswordConfirm}
                                                        onChange={(e) => { setSecPasswordConfirm(e.target.value); setSecError(''); }}
                                                        disabled={secBusy}
                                                        onKeyDown={(e) => {
                                                            if (e.key === 'Enter') {
                                                                e.preventDefault();
                                                                if (secPassword !== secPasswordConfirm) {
                                                                    setSecError('Passwords do not match.');
                                                                } else {
                                                                    commitModeSwitch('password', secPassword);
                                                                }
                                                            }
                                                        }}
                                                    />
                                                    <SmallButton
                                                        disabled={secBusy || !secPassword.trim()}
                                                        onClick={() => {
                                                            if (secPassword !== secPasswordConfirm) {
                                                                setSecError('Passwords do not match.');
                                                            } else {
                                                                commitModeSwitch('password', secPassword);
                                                            }
                                                        }}
                                                    >
                                                        {secBusy ? 'Encrypting...' : 'Set Password'}
                                                    </SmallButton>
                                                </InlinePasswordRow>
                                                {secError && <SecurityError>{secError}</SecurityError>}
                                            </div>
                                        )}
                                        {secSuccess && seedMode === 'password' && <SecuritySuccess><span>✓</span>{secSuccess}</SecuritySuccess>}

                                        <RadioLabel>
                                            <RadioInput
                                                name="seed_mode"
                                                value="memory"
                                                checked={seedMode === 'memory'}
                                                onChange={() => handleModeSelect('memory')}
                                                disabled={secBusy}
                                            />
                                            <span>
                                                Memory only
                                                <RadioDescription>Most secure. You must re-enter your 12-word phrase each session.</RadioDescription>
                                            </span>
                                        </RadioLabel>
                                        {secSuccess && seedMode === 'memory' && <SecuritySuccess><span>✓</span>{secSuccess}</SecuritySuccess>}

                                        <RadioLabel $disabled={!prfSupported}>
                                            <RadioInput
                                                name="seed_mode"
                                                value="passkey"
                                                checked={seedMode === 'passkey'}
                                                onChange={() => handleModeSelect('passkey')}
                                                disabled={secBusy || !prfSupported}
                                            />
                                            <span>
                                                Passkey (Touch ID / Face ID / Security Key)
                                                <RadioDescription>
                                                    {prfSupported
                                                        ? 'Seed encrypted with your passkey. Authenticate to unlock each session.'
                                                        : 'Requires Chrome, Edge, or Safari. Not supported in Firefox yet.'}
                                                </RadioDescription>
                                            </span>
                                        </RadioLabel>
                                        {secSuccess && seedMode === 'passkey' && <SecuritySuccess><span>✓</span>{secSuccess}</SecuritySuccess>}
                                    </RadioGroup>

                                    {secError && secPending !== 'password' && <SecurityError>{secError}</SecurityError>}
                                </ValueBox>
                            </Row>

                            {state.publicKey && (
                                <Row>
                                    <Label style={{ whiteSpace: 'normal' }}>Recovery phrase:</Label>
                                    <ValueBox>
                                        {!seedRevealed ? (
                                            <>
                                                <SmallButton
                                                    onClick={() => {
                                                        const s = seedVault.getSeed();
                                                        if (!s) {
                                                            setSecError('No seed phrase available. Please sign in first.');
                                                            return;
                                                        }
                                                        setSeedRevealed(true);
                                                        setSeedCopied(false);
                                                    }}
                                                >
                                                    Reveal Recovery Phrase
                                                </SmallButton>
                                                <ExplanationText>Show your 12-word recovery phrase so you can back it up.</ExplanationText>
                                            </>
                                        ) : (
                                            <>
                                                <SeedWarning>
                                                    Anyone with this phrase can access your account. Do not share it. It will be hidden automatically after 60 seconds.
                                                </SeedWarning>
                                                <SeedGrid>
                                                    {(seedVault.getSeed() || '').split(' ').map((word, i) => (
                                                        <SeedWord key={i} data-index={i + 1}>
                                                            {word}
                                                        </SeedWord>
                                                    ))}
                                                </SeedGrid>
                                                <div style={{ display: 'flex', gap: '0.5rem', marginTop: '0.35rem' }}>
                                                    <SmallButton
                                                        onClick={async () => {
                                                            try {
                                                                await navigator.clipboard.writeText(seedVault.getSeed() || '');
                                                                setSeedCopied(true);
                                                                setTimeout(() => setSeedCopied(false), 2000);
                                                            } catch (_) { }
                                                        }}
                                                    >
                                                        {seedCopied ? 'Copied!' : 'Copy'}
                                                    </SmallButton>
                                                    <SmallButton
                                                        onClick={() => { setSeedRevealed(false); setSeedCopied(false); }}
                                                        style={{ background: 'transparent', border: '1px solid #555', color: '#ccc' }}
                                                    >
                                                        Hide
                                                    </SmallButton>
                                                </div>
                                            </>
                                        )}
                                    </ValueBox>
                                </Row>
                            )}

                            <Divider />

                            <Row>
                                <Label>Theme:</Label>
                                <ValueBox>
                                    <ThemeSelect value={themeMode} onChange={handleThemeModeChange}>
                                        <option value="time">Time-based</option>
                                        <option value="dark">Dark</option>
                                        <option value="light">Light</option>
                                        <option value="system">System</option>
                                    </ThemeSelect>
                                    <ExplanationText>{getThemeExplanation(themeMode)}</ExplanationText>
                                </ValueBox>
                            </Row>

                            <Row>
                                <Label>Full width:</Label>
                                <ValueBox>
                                    <CheckboxLabel>
                                        <CheckboxInput
                                            checked={fullWidthMode}
                                            onChange={(e) => {
                                                const val = !!e.target.checked;
                                                setFullWidthMode(val);
                                                Storage.save('full_width_mode', val);
                                            }}
                                        />
                                        Expand cards to full screen width
                                    </CheckboxLabel>
                                </ValueBox>
                            </Row>

                            <Row>
                                <Label style={{ whiteSpace: 'normal' }}>Referral links:</Label>
                                <ValueBox>
                                    <CheckboxLabel>
                                        <CheckboxInput
                                            checked={referralPrecheckEnabled}
                                            disabled={referralPrecheckBusy}
                                            onChange={(e) => handleReferralPrecheckToggle(!!e.target.checked)}
                                        />
                                        Enable referral links for my account
                                    </CheckboxLabel>
                                    <ExplanationText>
                                        Lets people sign up via your personal link instead of sharing invite codes directly. Anyone with the link can use your codes, so leave this off if you want to hand them out manually.
                                    </ExplanationText>
                                    {referralPrecheckError && <SecurityError>{referralPrecheckError}</SecurityError>}
                                    {referralPrecheckSuccess && <SecuritySuccess><span>✓</span>{referralPrecheckSuccess}</SecuritySuccess>}
                                </ValueBox>
                            </Row>

                            <Row>
                                <Label style={{ whiteSpace: 'normal' }}>Show content with tags:</Label>
                                <ValueBox>
                                    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
                                        <CheckboxLabel>
                                            <CheckboxInput
                                                checked={showTagSensitive}
                                                onChange={(e) => {
                                                    const val = !!e.target.checked;
                                                    setShowTagSensitive(val);
                                                    Storage.save('show_tag_sensitive', val);
                                                    window.dispatchEvent(new CustomEvent('settingsUpdated', { detail: { showTagSensitive: val } }));
                                                }}
                                            />
                                            Sensitive
                                        </CheckboxLabel>
                                        <CheckboxLabel>
                                            <CheckboxInput
                                                checked={showTagPorn}
                                                onChange={(e) => {
                                                    const val = !!e.target.checked;
                                                    setShowTagPorn(val);
                                                    Storage.save('show_tag_porn', val);
                                                    window.dispatchEvent(new CustomEvent('settingsUpdated', { detail: { showTagPorn: val } }));
                                                }}
                                            />
                                            Porn
                                        </CheckboxLabel>
                                        <CheckboxLabel>
                                            <CheckboxInput
                                                checked={showTagViolence}
                                                onChange={(e) => {
                                                    const val = !!e.target.checked;
                                                    setShowTagViolence(val);
                                                    Storage.save('show_tag_violence', val);
                                                    window.dispatchEvent(new CustomEvent('settingsUpdated', { detail: { showTagViolence: val } }));
                                                }}
                                            />
                                            Violence
                                        </CheckboxLabel>
                                        <CheckboxLabel>
                                            <CheckboxInput
                                                checked={showTagGore}
                                                onChange={(e) => {
                                                    const val = !!e.target.checked;
                                                    setShowTagGore(val);
                                                    Storage.save('show_tag_gore', val);
                                                    window.dispatchEvent(new CustomEvent('settingsUpdated', { detail: { showTagGore: val } }));
                                                }}
                                            />
                                            Gore
                                        </CheckboxLabel>
                                        <CheckboxLabel>
                                            <CheckboxInput
                                                checked={showTagDeath}
                                                onChange={(e) => {
                                                    const val = !!e.target.checked;
                                                    setShowTagDeath(val);
                                                    Storage.save('show_tag_death', val);
                                                    window.dispatchEvent(new CustomEvent('settingsUpdated', { detail: { showTagDeath: val } }));
                                                }}
                                            />
                                            Death
                                        </CheckboxLabel>
                                    </div>
                                </ValueBox>
                            </Row>

                            <Row>
                                <Label style={{ whiteSpace: 'normal' }}>Blur sensitive media:</Label>
                                <ValueBox>
                                    <CheckboxLabel>
                                        <CheckboxInput
                                            checked={blurSensitiveMedia}
                                            onChange={(e) => {
                                                const val = !!e.target.checked;
                                                setBlurSensitiveMedia(val);
                                                Storage.save('blur_sensitive_media', val);
                                                window.dispatchEvent(new CustomEvent('settingsUpdated', { detail: { blurSensitiveMedia: val } }));
                                            }}
                                        />
                                        Blur tagged sensitive media (images/videos)
                                    </CheckboxLabel>
                                </ValueBox>
                            </Row>

                            <Row>
                                <Label>Auto-collapse:</Label>
                                <ValueBox>
                                    <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
                                        <ThemeSelect
                                            value={Number.isFinite(collapseThreshold) ? String(collapseThreshold) : '-5'}
                                            onChange={(e) => handleCollapseThresholdChange({ target: { value: e.target.value } })}
                                            style={{ width: 'auto', minWidth: '5rem' }}
                                        >
                                            <option value="-3">-3</option>
                                            <option value="-5">-5</option>
                                            <option value="-10">-10</option>
                                            <option value="-25">-25</option>
                                            <option value="-50">-50</option>
                                            <option value="0">Never</option>
                                        </ThemeSelect>
                                        <HelperText>
                                            Collapse comments at or below this score
                                        </HelperText>
                                    </div>
                                </ValueBox>
                            </Row>

                            <Row>
                                <Label>Sidebar topics:</Label>
                                <ValueBox>
                                    <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
                                        <ThemeSelect
                                            value={String(sidebarTopicsLimit)}
                                            onChange={handleSidebarTopicsLimitChange}
                                            style={{ width: 'auto', minWidth: '5rem' }}
                                        >
                                            <option value="5">5</option>
                                            <option value="10">10</option>
                                            <option value="15">15</option>
                                            <option value="20">20</option>
                                            <option value="50">50</option>
                                            <option value="100">100</option>
                                        </ThemeSelect>
                                        <HelperText>
                                            Topics shown in sidebar before "show more"
                                        </HelperText>
                                    </div>
                                </ValueBox>
                            </Row>

                            <Row>
                                <Label>Sidebar people:</Label>
                                <ValueBox>
                                    <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
                                        <ThemeSelect
                                            value={String(sidebarPeopleLimit)}
                                            onChange={handleSidebarPeopleLimitChange}
                                            style={{ width: 'auto', minWidth: '5rem' }}
                                        >
                                            <option value="5">5</option>
                                            <option value="10">10</option>
                                            <option value="15">15</option>
                                            <option value="20">20</option>
                                            <option value="50">50</option>
                                            <option value="100">100</option>
                                        </ThemeSelect>
                                        <HelperText>
                                            People shown in sidebar before "show more"
                                        </HelperText>
                                    </div>
                                </ValueBox>
                            </Row>

                            <Row>
                                <Label style={{ whiteSpace: 'normal' }}>Hide posts you downvote:</Label>
                                <ValueBox>
                                    <CheckboxLabel>
                                        <CheckboxInput
                                            checked={hideDownvotedPosts}
                                            onChange={(e) => {
                                                const val = !!e.target.checked;
                                                setHideDownvotedPosts(val);
                                                Storage.save('hide_downvoted_posts', val);
                                                window.dispatchEvent(new CustomEvent('settingsUpdated', { detail: { hideDownvotedPosts: val } }));
                                            }}
                                        />
                                        Immediately hide downvoted posts
                                    </CheckboxLabel>
                                </ValueBox>
                            </Row>

                            <Divider />

                            <Row>
                                <Label style={{ whiteSpace: 'normal' }}>Delete account:</Label>
                                <ValueBox>
                                    <DangerNotice>
                                        This submits an account deletion request to the network. Most nodes will honor it, but some may not — full removal cannot be guaranteed.
                                    </DangerNotice>
                                    <DangerRow>
                                        <DangerInput
                                            value={deleteConfirmText}
                                            onChange={(e) => {
                                                setDeleteConfirmText(e.target.value);
                                                if (deleteError) setDeleteError('');
                                                if (deleteSuccess) setDeleteSuccess('');
                                            }}
                                            onKeyDown={(e) => {
                                                if (e.key === 'Enter') {
                                                    e.preventDefault();
                                                    handleDeleteAccount();
                                                }
                                            }}
                                            placeholder="Type DELETE to confirm"
                                            disabled={deleteBusy}
                                        />
                                        <DangerButton
                                            disabled={!deleteConfirmReady || deleteBusy}
                                            onClick={handleDeleteAccount}
                                        >
                                            {deleteStatus || (deleteBusy ? 'Deleting...' : 'Delete account')}
                                        </DangerButton>
                                    </DangerRow>
                                    {deleteError && <SecurityError>{deleteError}</SecurityError>}
                                    {deleteSuccess && <SecuritySuccess><span>✓</span>{deleteSuccess}</SecuritySuccess>}
                                </ValueBox>
                            </Row>

                        </ContainerBody>
                    </TabbedContainer>
                </ModernPostFeed>
            </div>
        </ContentGrid>
    );
}
