import React, { useState } from "react";
import { Helmet } from 'react-helmet-async';
import styled from "styled-components"
import Button from "../components/Button";
import { useNavigate, useLocation } from 'react-router-dom';
import { generateMnemonic } from 'bip39';
import Storage from "../utils/Storage.js";
import seedVault from "../utils/SeedVault.js";
import { updateNotification } from "../utils/notifications.js";
import { deriveKeysFromSeed } from '../utils/CryptoUtils.js';
import * as tx from "../utils/tx";
import Api from '../lib/api';
import AuthPageShell from "../components/AuthPageShell";
import Sidebar from "../components/Sidebar";
import TopBar from "../components/TopBar";
import MobileHeader from "../components/MobileHeader";
import { ContentGrid, ModernPostFeed } from "../styled/Layout";
import { getMaxUsernameSize, getMinUsernameSize, getMaxInputLength } from "../config/chainParams";

const Centered = styled.div`
    text-align: center;
    max-width: 800px;
    margin: 0 auto;
    padding: 0 0.5rem;
`

const StyledInfo = styled.div`
    margin-top: 0.5rem;
    margin-left: 0;
    margin-right: 0;
    padding: 1.5rem 1.25rem;
    background-color: ${({ theme }) => theme?.colors?.panelAlt || '#2A2E33'};
    border: 1px solid ${({ theme }) => theme?.colors?.border || '#444'};
    border-radius: 8px;
    text-align: center;
    
    @media (max-width: 1000px) {
        padding: 1rem 0.75rem;
    }
`

const StyledInputBox = styled.input`    
    border: 1px solid ${({ theme }) => theme?.colors?.text || 'white'};
    display: block;
    width: 100%;
    max-width: 320px;
    margin: 8px auto;    
    background-color: ${({ theme }) => theme?.colors?.panel || '#23272C'};
    color: ${({ theme }) => theme?.colors?.subtleText || '#CCC'};
    text-align: center;
    resize: none;
    font-size: 0.7rem;
    line-height: 1.0;
    padding: 0.15rem 0.35rem;
    box-sizing: border-box;

    &:hover,&:focus {
        background-color: ${({ theme }) => theme?.colors?.panelAlt || '#33373C'};
    }
`

const ButtonWrapper = styled.div`
    display: flex;
    justify-content: center;
    margin: 6px auto;
    max-width: 320px;
`


const IntroP = styled.p`
    margin: 0 0 1rem 0;
    line-height: 1.6;
    font-size: 0.85rem;
    color: ${({ theme }) => theme?.colors?.text || '#e5e7eb'};
    max-width: 800px;
    text-align: justify;
    text-align-last: center;
    
    &:last-of-type {
        margin-bottom: 0;
    }
    
    @media (max-width: 1000px) {
        /* Root font is 130% on mobile, so use smaller rem to compensate */
        font-size: 0.6rem;
        line-height: 1.5;
    }
`;

const WelcomeTitle = styled.div`
    font-size: 1.5rem;
    font-weight: 600;
    margin-bottom: 1.25rem;
    color: ${({ theme }) => theme?.colors?.text || '#e5e7eb'};
    text-align: center;
    @media (max-width: 1000px) {
        font-size: 1.25rem;
        margin-bottom: 1rem;
    }
`;

const UsernameLabel = styled.div`
    font-size: 1.0rem;
    font-weight: 600;
    margin-top: 1.75rem;
    margin-bottom: 0.75rem;
    color: ${({ theme }) => theme?.colors?.text || '#e5e7eb'};
`;

function CreateAccountView({ state, setCredentials }) {
    const navigate = useNavigate();
    const location = useLocation();
    const [configUpdateTrigger, setConfigUpdateTrigger] = React.useState(0);

    // Re-read config when App.js fetches fresh data
    React.useEffect(() => {
        const handler = () => setConfigUpdateTrigger(prev => prev + 1);
        window.addEventListener('configUpdated', handler);
        return () => window.removeEventListener('configUpdated', handler);
    }, []);

    // Read node config from localStorage (set by get_config API)
    // Both fields must be explicitly present (boolean) — no silent defaults.
    const nodeConfig = React.useMemo(() => {
        void configUpdateTrigger;
        try {
            const raw = localStorage.getItem('configData');
            if (raw) {
                const parsed = JSON.parse(raw);
                if (typeof parsed.registration_enabled === 'boolean' &&
                    typeof parsed.registration_invite_code_required === 'boolean') {
                    return parsed;
                }
            }
        } catch (_) { }
        return null;  // null = config not loaded
    }, [configUpdateTrigger]);
    const registrationEnabled = nodeConfig ? nodeConfig.registration_enabled : false;
    const inviteCodeRequired = nodeConfig ? nodeConfig.registration_invite_code_required : false;

    // If nodeConfig is missing (stale cache or empty localStorage), fetch it ourselves.
    // App.js may skip the fetch if it thinks params are valid and not stale (24h TTL).
    React.useEffect(() => {
        if (nodeConfig) return;
        (async () => {
            try {
                const cfg = await Api.get('get_config', undefined, { timeoutMs: 10000 });
                if (!cfg || typeof cfg !== 'object') return;
                try { await tx.cacheConfigData(cfg); } catch (_) { }
            } catch (_) { }
        })();
    }, [nodeConfig]);

    // Check if we're coming from login with an imported seed (account not found on chain)
    const importedSeed = location.state?.importedSeed || null;
    const fromRecovery = location.state?.fromRecovery || false;

    // Get invite code from URL parameter if present
    const urlParams = new URLSearchParams(location.search);
    const inviteFromUrl = urlParams.get('invite') || '';

    // If user is already signed in, redirect to their profile
    React.useEffect(() => {
        if (state.publicKey) {
            navigate('/profile', { replace: true });
        }
    }, [state.publicKey, navigate]);

    // Set up state for seed_phrase and publicKey (privateKey derived from seed)
    const [seedPhrase, setSeedPhrase] = useState("");
    const [publicKey, setPublicKey] = useState("");
    const [inviteCode, setInviteCode] = useState(() => {
        // Pre-populate from URL if present, format it properly
        if (inviteFromUrl) {
            const clean = inviteFromUrl.toUpperCase().replace(/[^A-Z0-9]/g, '').slice(0, 8);
            return clean.length > 4 ? clean.slice(0, 4) + '-' + clean.slice(4) : clean;
        }
        return "";
    });
    const [usernameInput, setUsernameInput] = useState("");
    const [submitting, setSubmitting] = useState(false);
    const [buttonStatus, setButtonStatus] = useState("idle");
    const [statusStartTime, setStatusStartTime] = useState(null);
    const [elapsedTime, setElapsedTime] = useState(0);
    const [submitError, setSubmitError] = useState("");
    const [cooldownUntil, setCooldownUntil] = useState(0);

    // While submitting/confirming, block all clicks and key navigation globally
    React.useEffect(() => {
        if (!submitting) return;
        // Blur any focused element to remove the blinking cursor
        if (document.activeElement && document.activeElement.blur) {
            document.activeElement.blur();
        }
        const blocker = (e) => { try { e.preventDefault(); e.stopPropagation(); } catch (_) { } };
        document.addEventListener('click', blocker, true);
        document.addEventListener('keydown', blocker, true);
        document.addEventListener('pointerdown', blocker, true);
        document.addEventListener('touchstart', blocker, true);
        return () => {
            document.removeEventListener('click', blocker, true);
            document.removeEventListener('keydown', blocker, true);
            document.removeEventListener('pointerdown', blocker, true);
            document.removeEventListener('touchstart', blocker, true);
        };
    }, [submitting]);

    // Update elapsed time every 100ms when a status is active
    React.useEffect(() => {
        if (!statusStartTime || buttonStatus === "idle") {
            setElapsedTime(0);
            return;
        }
        const interval = setInterval(() => {
            setElapsedTime((Date.now() - statusStartTime) / 1000);
        }, 100);
        return () => clearInterval(interval);
    }, [statusStartTime, buttonStatus]);


    // Check username availability via backend (10s timeout)
    const checkUsernameAvailable = async (rawName) => {
        try {
            const base = String(rawName || "").trim();
            if (!base) return { available: false, error: "empty" };
            const data = await Api.get('get_address_from_username', { username: base }, { timeoutMs: 10000 });
            const available = !!(data && !data.exists); // exists=true means taken, so available=!exists
            return { available, error: null };
        } catch (e) {
            return { available: false, error: String(e && e.message && e.message.includes('timeout') ? 'timeout' : 'network') };
        }
    };

    // Validate invite code via backend
    const validateInviteCode = async (code) => {
        try {
            const resp = await Api.post('validate_invite_code', { code }, { timeoutMs: 10000 });
            if (resp && resp.valid) {
                return { valid: true, owner: resp.owner };
            }
            return { valid: false, error: resp?.error || 'Invalid invite code' };
        } catch (e) {
            return { valid: false, error: 'Could not validate invite code' };
        }
    };

    // Function to initialize account (use imported seed or generate new)
    const initializeAccount = (existingSeed = null) => {
        // Preserve referrer before clearing storage
        const referrer = localStorage.getItem('referrer_address');
        Storage.clear();
        // Restore referrer after clearing
        if (referrer) {
            localStorage.setItem('referrer_address', referrer);
        }

        // Use provided seed or generate new one
        const newSeedPhrase = existingSeed || generateMnemonic();
        setSeedPhrase(newSeedPhrase);

        try {
            // Derive public key/address from seed phrase
            const { publicKey: address } = deriveKeysFromSeed(newSeedPhrase);
            setPublicKey(address);
        } catch (error) {
            setSubmitError("Key derivation failed: " + error.message);
        }
    };

    // Call initializeAccount on component mount only if we don't have data yet and user is not signed in
    React.useEffect(() => {
        if (!seedPhrase && !publicKey && !state.publicKey) {
            initializeAccount(importedSeed);
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [state.publicKey, importedSeed]);

    // Clear any pending username/publicKey if this view unmounts
    React.useEffect(() => {
        return () => {
            try { Storage.remove('username_pending'); } catch (_) { }
            try { Storage.remove('publicKey_pending'); } catch (_) { }
        };
    }, []);

    // Build canonical bytes for MsgSetUsername (must match chain ante)

    // Handle the continue button: fetch PoW params, compute PoW, sign relay and relay
    const handleContinue = async (event) => {
        event.preventDefault();
        if (Date.now() < cooldownUntil) return;
        if (!publicKey || !seedPhrase) return;
        const base = (usernameInput || "").trim();
        if (!base) return;

        const usernameFinal = `Anon-${base}`;

        // Validate username length (use defaults if params not cached yet)
        const minSize = getMinUsernameSize() ?? 5;
        const maxSize = getMaxUsernameSize() ?? 30;
        if (usernameFinal.length < minSize) {
            setSubmitError(`Username too short. Minimum ${minSize} characters required (you have ${usernameFinal.length}).`);
            const until = Date.now() + 1000;
            setCooldownUntil(until);
            setTimeout(() => setCooldownUntil(0), 1000);
            return;
        }
        if (usernameFinal.length > maxSize) {
            setSubmitError(`Username too long. Maximum ${maxSize} characters allowed (you have ${usernameFinal.length}).`);
            const until = Date.now() + 1000;
            setCooldownUntil(until);
            setTimeout(() => setCooldownUntil(0), 1000);
            return;
        }

        // Validate invite code only when required by node config
        let codeClean = null;
        if (inviteCodeRequired) {
            codeClean = (inviteCode || "").trim().toUpperCase();
            if (!codeClean || codeClean.length !== 9 || codeClean[4] !== '-') {
                setSubmitError("Please enter a valid invite code (format: XXXX-XXXX)");
                const until = Date.now() + 1000;
                setCooldownUntil(until);
                setTimeout(() => setCooldownUntil(0), 1000);
                return;
            }

            setSubmitError("");
            const inviteRes = await validateInviteCode(codeClean);
            if (!inviteRes || !inviteRes.valid) {
                setSubmitError(inviteRes?.error || "Invalid invite code");
                const until = Date.now() + 1000;
                setCooldownUntil(until);
                setTimeout(() => setCooldownUntil(0), 1000);
                return;
            }
        }

        // Preflight: ensure username is still available
        const availRes = await checkUsernameAvailable(usernameFinal);
        if (!availRes || availRes.error) {
            setSubmitError("Cannot check username – server unavailable");
            const until = Date.now() + 1000;
            setCooldownUntil(until);
            setTimeout(() => setCooldownUntil(0), 1000);
            return;
        }
        if (!availRes.available) {
            setSubmitError("Username already taken");
            const until = Date.now() + 1000;
            setCooldownUntil(until);
            setTimeout(() => setCooldownUntil(0), 1000);
            return;
        }
        // Show optimistic username and session in header immediately
        try { Storage.save('username_pending', usernameFinal); } catch (_) { }
        try { Storage.save('publicKey_pending', publicKey); } catch (_) { }
        // Stage 1: Preparing (PoW + transaction creation)
        setSubmitting(true);
        setButtonStatus("preparing");
        setStatusStartTime(Date.now());
        await new Promise(r => setTimeout(r, 50)); // Let React render
        try {
            // Persist fresh credentials so TransactionHandler uses the correct signer
            try {
                seedVault.storeSeed(seedPhrase, 'insecure', null);
                // Do not persist publicKey until confirmation
            } catch (_) { }
            // Defer to tx facade for PoW + relay
            // Pass invite code so backend marks it as used atomically with account creation
            const result = await tx.createUser(usernameFinal, codeClean);
            if (!result || !result.success) {
                const msg = String((result && result.error) || "Submit failed");
                if (/admin insufficient balance/i.test(msg)) {
                    setSubmitError("Your account balance is too low to cover the transaction fee.");
                } else if (/insufficient funds/i.test(msg)) {
                    setSubmitError("Unfortunately the node does not have enough gas available to complete this transaction.");
                } else {
                    setSubmitError(msg);
                }
                const until = Date.now() + 1000;
                setCooldownUntil(until);
                setTimeout(() => setCooldownUntil(0), 1000);
                setSubmitting(false);
                setButtonStatus("idle");
                setStatusStartTime(null);
                try { Storage.remove('username_pending'); } catch (_) { }
                try { Storage.remove('publicKey_pending'); } catch (_) { }
                // Do not sign out on initial submit failure; let user retry
                return;
            }

            // Stage 2: Submitting (show for 1-2 seconds)
            setButtonStatus("submitting");
            setStatusStartTime(Date.now());
            await new Promise(r => setTimeout(r, 50)); // Let React render
            const submittingDuration = 1000 + Math.random() * 1000; // 1.0 to 2.0 seconds
            await new Promise(r => setTimeout(r, submittingDuration));

            // Stage 3: Verifying (4s initial, then 2s intervals, max 5 attempts)
            setButtonStatus("verifying");
            setStatusStartTime(Date.now());
            await new Promise(r => setTimeout(r, 50)); // Let React render
            // Confirm on-chain before establishing session
            try {
                const txHash = (result && result.tx_hash) ? String(result.tx_hash).toLowerCase() : "";
                if (!txHash) throw new Error("missing tx hash");
                const pollResult = await tx.pollTxStatus(txHash);
                if (!pollResult) throw new Error('confirmation timeout');
                if (!pollResult.success) {
                    throw new Error(pollResult.error_details?.message || 'transaction rejected');
                }
                // Invite code is now marked as used by the backend in the set_username call
                // Navigate to welcome FIRST (before setCredentials triggers useEffect redirect to /profile)
                const finalUsername = `Anon-${base}`;
                try { Storage.remove('username_pending'); } catch (_) { }
                try { Storage.remove('publicKey_pending'); } catch (_) { }
                navigate('/welcome', { state: { username: finalUsername, seedPhrase }, replace: true });
                // Establish session after navigation
                setCredentials(publicKey, finalUsername, seedPhrase);
            } catch (e) {
                setSubmitError(String(e && e.message ? e.message : 'Failed to confirm account on-chain'));
                try { Storage.remove('username_pending'); } catch (_) { }
                try { Storage.remove('publicKey_pending'); } catch (_) { }
                updateNotification('There was an error creating your account. You have been signed out.', 5.0, true);
                setButtonStatus("idle");
                setStatusStartTime(null);
                navigate('/sign_out');
            }
            // Persist some context for later
            try { localStorage.setItem('user_balance', String(localStorage.getItem('user_balance') || '0')); } catch (_) { }
        } catch (e) {
            setSubmitError(String(e?.message || e || "Submit failed"));
            setButtonStatus("idle");
            setStatusStartTime(null);
        } finally {
            setSubmitting(false);
        }
    };

    const usernameFinal = (usernameInput || "").trim();

    // Node config must be loaded before we can show anything.
    // configUpdateTrigger > 0 means the configUpdated event fired at least once (fetch finished).
    const configFetchDone = configUpdateTrigger > 0;
    if (!nodeConfig) {
        return (
            <ContentGrid>
                <Helmet>
                    <title>Create Account | Mirage</title>
                </Helmet>
                <Sidebar currentPath={location.pathname} state={state} />
                <div>
                    <TopBar state={state} />
                    <ModernPostFeed>
                        <MobileHeader />
                        <AuthPageShell activeTab="create">
                            <Centered>
                                <StyledInfo>
                                    {configFetchDone ? (
                                        <>
                                            <WelcomeTitle>Unavailable</WelcomeTitle>
                                            <IntroP>
                                                Unable to load node configuration. Please refresh the page.
                                            </IntroP>
                                        </>
                                    ) : (
                                        <WelcomeTitle>Loading...</WelcomeTitle>
                                    )}
                                </StyledInfo>
                            </Centered>
                        </AuthPageShell>
                    </ModernPostFeed>
                </div>
            </ContentGrid>
        );
    }

    // If registration is disabled on this node, show unavailable message
    if (!registrationEnabled) {
        return (
            <ContentGrid>
                <Helmet>
                    <title>Create Account | Mirage</title>
                </Helmet>
                <Sidebar currentPath={location.pathname} state={state} />
                <div>
                    <TopBar state={state} />
                    <ModernPostFeed>
                        <MobileHeader />
                        <AuthPageShell activeTab="create">
                            <Centered>
                                <StyledInfo>
                                    <WelcomeTitle>Account Creation Unavailable</WelcomeTitle>
                                    <IntroP>
                                        Account creation is not available on this node.
                                    </IntroP>
                                </StyledInfo>
                            </Centered>
                        </AuthPageShell>
                    </ModernPostFeed>
                </div>
            </ContentGrid>
        );
    }

    return (
        <ContentGrid>
            <Helmet>
                <title>Create Account | Mirage</title>
            </Helmet>
            <Sidebar currentPath={location.pathname} state={state} />
            <div>
                <TopBar state={state} />
                <ModernPostFeed>
                    <MobileHeader />
                    <AuthPageShell activeTab="create">
                        <Centered>
                            <StyledInfo>
                                <WelcomeTitle>{fromRecovery ? 'Create Your Account' : 'Welcome to Mirage!'}</WelcomeTitle>
                                <div>
                                    {fromRecovery ? (
                                        <>
                                            <IntroP style={{ color: '#f66' }}>
                                                No account was found on the blockchain for this recovery phrase, but you can create a new account using it now.
                                            </IntroP>
                                            <IntroP>
                                                Free accounts are prefixed with "Anon-" and run a small proof-of-work on your device to prevent spam.
                                                Choose a username below to continue.
                                            </IntroP>
                                        </>
                                    ) : (
                                        <>
                                            <IntroP>
                                                Mirage is a fully decentralized social network built on its own blockchain, designed to be 100% censorship resistant.
                                            </IntroP>
                                            <IntroP>
                                                Free accounts are prefixed with "Anon-" and run a small proof-of-work on your device to prevent spam.
                                                You can upgrade anytime with MIRAGE tokens to remove the prefix, unlock cosmetic perks, and access premium features.
                                            </IntroP>
                                        </>
                                    )}
                                </div>
                                {inviteCodeRequired && (
                                    <>
                                        <UsernameLabel>Enter your invite code:</UsernameLabel>
                                        <StyledInputBox
                                            placeholder="XXXX-XXXX"
                                            value={inviteCode}
                                            onChange={(e) => {
                                                const raw = e.target.value.toUpperCase();
                                                // Only allow uppercase alphanumeric
                                                const alphanumOnly = raw.replace(/[^A-Z0-9]/g, "");
                                                // Limit to 8 alphanumeric chars
                                                const limited = alphanumOnly.slice(0, 8);
                                                // Auto-insert dash after 4 chars
                                                const formatted = limited.length > 4
                                                    ? limited.slice(0, 4) + '-' + limited.slice(4)
                                                    : limited;
                                                setInviteCode(formatted);
                                                setSubmitError("");
                                            }}
                                            maxLength={9}
                                            name="invite-code-entry"
                                            id="invite-code-entry"
                                            autoComplete="one-time-code"
                                            autoCorrect="off"
                                            autoCapitalize="characters"
                                            spellCheck="false"
                                            data-lpignore="true"
                                            data-1p-ignore="true"
                                            data-bwignore="true"
                                            data-form-type="other"
                                        />
                                    </>
                                )}
                                <UsernameLabel>Choose your username:</UsernameLabel>
                                <StyledInputBox
                                    placeholder=""
                                    value={usernameInput}
                                    onChange={(e) => {
                                        const raw = e.target.value;
                                        const cleaned = raw.replace(/[^A-Za-z0-9-]/g, "");
                                        const maxLen = getMaxInputLength(true);
                                        // If params not loaded yet, allow up to 100 chars temporarily
                                        setUsernameInput(cleaned.slice(0, maxLen ?? 100));
                                        setSubmitError("");
                                    }}
                                    onKeyDown={async (e) => {
                                        if (e.key === 'Enter') {
                                            e.preventDefault();
                                            await handleContinue(e);
                                        }
                                    }}
                                    onPaste={(e) => {
                                        // Block paste to prevent accidental seed phrase entry
                                        e.preventDefault();
                                    }}
                                    maxLength={getMaxInputLength(true) || 100}
                                    name="display-name-entry"
                                    id="display-name-entry"
                                    autoComplete="one-time-code"
                                    autoCorrect="off"
                                    autoCapitalize="off"
                                    spellCheck="false"
                                    data-lpignore="true"
                                    data-1p-ignore="true"
                                    data-bwignore="true"
                                    data-form-type="other"
                                />
                                <ButtonWrapper>
                                    <Button
                                        onClick={handleContinue}
                                        disabled={submitting || (Date.now() < cooldownUntil) || (usernameFinal.trim() === '')}
                                        fullWidth
                                        size="sm"
                                        loading={submitting}
                                    >
                                        {buttonStatus === "preparing" ? `Preparing... (${elapsedTime.toFixed(1)}s)` :
                                            buttonStatus === "submitting" ? `Submitting... (${elapsedTime.toFixed(1)}s)` :
                                                buttonStatus === "verifying" ? `Verifying... (${elapsedTime.toFixed(1)}s)` :
                                                    'Continue'}
                                    </Button>
                                </ButtonWrapper>
                                {submitError && (
                                    <div style={{ color: '#f66', marginTop: '0.5rem', fontSize: '0.8rem' }}>{submitError}</div>
                                )}
                            </StyledInfo>
                        </Centered>
                    </AuthPageShell>
                </ModernPostFeed>
            </div>
        </ContentGrid>
    );
}

export default CreateAccountView;