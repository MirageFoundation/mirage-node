import { useState, useEffect, useCallback } from "react";
import styled from "styled-components";
import { useLocation } from "react-router-dom";
import Storage from "../utils/Storage";
import seedVault from "../utils/SeedVault";
import { deleteUser } from "../utils/tx";
import Api from "../utils/api";
import { signPlainPayload } from "../utils/signPlain";
import usePendingDeletes from "./usePendingDeletes.js";
import { formatError } from "../utils/errorMessages";
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
      return Storage.load('theme_id', 'bluemoon');
    } catch (_) {
      return 'bluemoon';
    }
  });
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
  const [inviteCodesRequired, setInviteCodesRequired] = useState(() => {
    try {
      const nc = JSON.parse(localStorage.getItem('nodeConfig') || '{}');
      return !!nc.registration_invite_code_required;
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
      const modeLabels = {
        insecure: 'Unencrypted',
        password: 'Password',
        memory: 'Memory-only',
        passkey: 'Passkey'
      };
      setSecSuccess(`${modeLabels[newMode] || 'Storage'} storage updated.`);
      setTimeout(() => setSecSuccess(''), 5000);
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
    const readConfig = () => {
      try {
        const nc = JSON.parse(localStorage.getItem('nodeConfig') || '{}');
        setInviteCodesRequired(!!nc.registration_invite_code_required);
      } catch (_) {
        setInviteCodesRequired(false);
      }
    };
    window.addEventListener('nodeConfigUpdated', readConfig);
    return () => window.removeEventListener('nodeConfigUpdated', readConfig);
  }, []);
  useEffect(() => {
    if (!state.publicKey) return;
    let cancelled = false;
    Api.get('get_user_status', {
      address: state.publicKey,
      _cb: Date.now()
    }).then(data => {
      if (cancelled || !data) return;
      if (typeof data.referral_precheck_enabled === 'boolean') {
        setReferralPrecheckEnabled(data.referral_precheck_enabled);
        Storage.save('referral_precheck_enabled', data.referral_precheck_enabled);
      }
    }).catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [state.publicKey]);
  const handleThemeIdChange = e => {
    const newId = e.target.value;
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
  const handleReferralPrecheckToggle = async nextVal => {
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
        ...sig
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
  const handleSidebarTopicsLimitChange = e => {
    const n = Number(e.target.value);
    if (!Number.isFinite(n)) return;
    setSidebarTopicsLimit(n);
    Storage.save('sidebar_topics_limit', n);
    window.dispatchEvent(new CustomEvent('sidebarSettingsUpdated'));
  };
  const handleSidebarPeopleLimitChange = e => {
    const n = Number(e.target.value);
    if (!Number.isFinite(n)) return;
    setSidebarPeopleLimit(n);
    Storage.save('sidebar_people_limit', n);
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
    sidebarTopicsLimit,
    sidebarPeopleLimit,
    hideDownvotedPosts,
    setHideDownvotedPosts,
    blurSensitiveMedia,
    setBlurSensitiveMedia,
    showTagSensitive,
    setShowTagSensitive,
    showTagPorn,
    setShowTagPorn,
    showTagViolence,
    setShowTagViolence,
    showTagGore,
    setShowTagGore,
    showTagDeath,
    setShowTagDeath,
    fullWidthMode,
    setFullWidthMode,
    referralPrecheckEnabled,
    referralPrecheckBusy,
    referralPrecheckError,
    referralPrecheckSuccess,
    inviteCodesRequired,
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
    commitModeSwitch,
    handleModeSelect,
    handleThemeIdChange,
    handleThemeModeChange,
    handleReferralPrecheckToggle,
    handleCollapseThresholdChange,
    handleSidebarTopicsLimitChange,
    handleSidebarPeopleLimitChange,
    getThemeExplanation,
    handleDeleteAccount
  };
}