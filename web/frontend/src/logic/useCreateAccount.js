import React, { useState } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { generateMnemonic } from "bip39";
import Storage from "../utils/Storage.js";
import seedVault from "../utils/SeedVault.js";
import { deriveKeysFromSeed } from "../utils/CryptoUtils.js";
import * as tx from "../utils/tx";
import Api from "../utils/api";
import { getMaxUsernameSize, getMinUsernameSize } from "../utils/chainParams";
import { formatError } from "../utils/errorMessages";
import { clearReferralAttribution, getReferralAttribution } from "../utils/visitorId";
export function useCreateAccount({
    state,
    setCredentials
}) {
    const navigate = useNavigate();
    const location = useLocation();
    const [configUpdateTrigger, setConfigUpdateTrigger] = React.useState(0);
    const configFetchAttemptedRef = React.useRef(false);

    // Re-read config when App.js fetches fresh data
    React.useEffect(() => {
        const handler = () => setConfigUpdateTrigger(prev => prev + 1);
        window.addEventListener('nodeConfigUpdated', handler);
        return () => window.removeEventListener('nodeConfigUpdated', handler);
    }, []);

    // Read node config from localStorage (set by get_node_config API)
    // Both fields must be explicitly present (boolean) — no silent defaults.
    const nodeConfig = React.useMemo(() => {
        void configUpdateTrigger;
        try {
            const raw = localStorage.getItem('nodeConfig');
            if (raw) {
                const parsed = JSON.parse(raw);
                if (typeof parsed.registration_enabled === 'boolean' && typeof parsed.registration_invite_code_required === 'boolean') {
                    return parsed;
                }
            }
        } catch (_) { }
        return null; // null = config not loaded
    }, [configUpdateTrigger]);
    const registrationEnabled = nodeConfig ? nodeConfig.registration_enabled : false;
    const inviteCodeRequired = nodeConfig ? nodeConfig.registration_invite_code_required : false;

    // App.js fetches get_node_config on mount when stale and fires nodeConfigUpdated.
    // If config is missing (cleared or never cached), fetch here once to avoid
    // a permanent "Loading..." state on this view.
    React.useEffect(() => {
        if (nodeConfig || configFetchAttemptedRef.current) return;
        configFetchAttemptedRef.current = true;
        let cancelled = false;
        try {
            console.debug('[CreateAccount] nodeConfig missing, fetching...');
        } catch (_) { }
        Api.get('get_node_config', undefined).then(cfg => {
            if (!cfg || typeof cfg !== 'object') {
                try {
                    console.warn('[CreateAccount] nodeConfig fetch returned invalid payload');
                } catch (_) { }
                return;
            }
            try {
                tx.cacheNodeConfig(cfg);
            } catch (_) { }
        }).catch(err => {
            try {
                console.error('[CreateAccount] nodeConfig fetch failed:', err);
            } catch (_) { }
        }).finally(() => {
            if (cancelled) return;
            // Ensure we exit the loading state even if fetch failed.
            setConfigUpdateTrigger(prev => prev + 1);
        });
        return () => {
            cancelled = true;
        };
    }, [nodeConfig]);

    // Check if we're coming from login with an imported seed (account not found on chain)
    const importedSeed = location.state?.importedSeed || null;
    const fromRecovery = location.state?.fromRecovery || false;

    // Get invite code and referrer from URL parameters
    const urlParams = new URLSearchParams(location.search);
    const inviteFromUrl = urlParams.get('invite') || '';
    const inviteChars = inviteFromUrl.toUpperCase().replace(/[^A-Z0-9]/g, '').slice(0, 8);
    const formattedInviteFromUrl = inviteChars.length > 4
        ? `${inviteChars.slice(0, 4)}-${inviteChars.slice(4)}`
        : inviteChars;
    const hasValidInviteFromUrl = /^[A-Z0-9]{4}-[A-Z0-9]{4}$/.test(formattedInviteFromUrl);
    const explicitReferrer = urlParams.get('ref') || '';
    const refFromUrl = hasValidInviteFromUrl ? '' : explicitReferrer || getReferralAttribution();

    // If user is already signed in, redirect to their profile
    React.useEffect(() => {
        if (state.publicKey) {
            navigate('/profile', {
                replace: true
            });
        }
    }, [state.publicKey, navigate]);

    // Set up state for seed_phrase and publicKey (privateKey derived from seed)
    const [seedPhrase, setSeedPhrase] = useState("");
    const [publicKey, setPublicKey] = useState("");
    const [inviteCode, setInviteCode] = useState(formattedInviteFromUrl);
    const [usernameInput, setUsernameInput] = useState("");
    const [submitting, setSubmitting] = useState(false);
    const [buttonStatus, setButtonStatus] = useState("idle");
    const [statusStartTime, setStatusStartTime] = useState(null);
    const [, setElapsedTime] = useState(0);
    const [submitError, setSubmitError] = useState("");
    const [cooldownUntil, setCooldownUntil] = useState(0);

    // Referral attribution survives navigation in a short-lived first-party cookie.
    const [referrerUsername, setReferrerUsername] = useState(refFromUrl);
    const [referrerStatus, setReferrerStatus] = useState(refFromUrl ? "checking" : "none");
    const [referrerAvailable, setReferrerAvailable] = useState(0);
    const [referrerError, setReferrerError] = useState("");

    // Invite-gated nodes pre-check whether the referrer can supply the invite.
    // Open-registration nodes still submit the referrer for attribution.
    React.useEffect(() => {
        if (!refFromUrl) return;
        setReferrerUsername(refFromUrl);
        if (!inviteCodeRequired) {
            setReferrerStatus("valid");
            return;
        }
        if (hasValidInviteFromUrl) {
            setReferrerStatus("none");
            return;
        }
        let cancelled = false;
        setReferrerStatus("checking");
        Api.get('referrals/precheck', {
            username: refFromUrl
        }).then(data => {
            if (cancelled) return;
            if (data && data.valid) {
                setReferrerUsername(refFromUrl);
                setReferrerStatus("valid");
                if (typeof data.available === 'number') setReferrerAvailable(data.available);
            } else {
                setReferrerStatus("none");
                setReferrerError(data || "referrer_check_failed");
            }
        }).catch(() => {
            if (cancelled) return;
            setReferrerStatus("none");
            setReferrerError("referrer_check_failed");
        });
        return () => {
            cancelled = true;
        };
    }, [hasValidInviteFromUrl, inviteCodeRequired, refFromUrl]);

    // While submitting/confirming, block all clicks and key navigation globally
    React.useEffect(() => {
        if (!submitting) return;
        // Blur any focused element to remove the blinking cursor
        if (document.activeElement && document.activeElement.blur) {
            document.activeElement.blur();
        }
        const blocker = e => {
            try {
                e.preventDefault();
                e.stopPropagation();
            } catch (_) { }
        };
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
    const checkUsernameAvailable = async rawName => {
        try {
            const base = String(rawName || "").trim();
            if (!base) return {
                available: false,
                error: "empty"
            };
            const data = await Api.get('get_address_from_username', {
                username: base
            });
            const available = !!(data && !data.exists); // exists=true means taken, so available=!exists
            return {
                available,
                error: null
            };
        } catch (e) {
            return {
                available: false,
                error: String(e && e.message && e.message.includes('timeout') ? 'timeout' : 'network')
            };
        }
    };

    // Validate invite code via backend
    const validateInviteCode = async code => {
        try {
            const resp = await Api.post('validate_invite_code', {
                code
            });
            if (resp && resp.valid) {
                return {
                    valid: true,
                    owner: resp.owner
                };
            }
            return resp || {
                valid: false,
                error_code: "invite_code_invalid",
                error: "invalid invite code"
            };
        } catch (e) {
            return {
                valid: false,
                error_code: "invite_code_check_failed",
                error: "failed to validate invite code"
            };
        }
    };
    const initializeAccount = (existingSeed = null) => {
        Storage.clear();
        const newSeedPhrase = existingSeed || generateMnemonic();
        setSeedPhrase(newSeedPhrase);
        try {
            // Derive public key/address from seed phrase
            const {
                publicKey: address
            } = deriveKeysFromSeed(newSeedPhrase);
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
            try {
                Storage.remove('username_pending');
            } catch (_) { }
            try {
                Storage.remove('publicKey_pending');
            } catch (_) { }
        };
    }, []);

    // Build canonical bytes for MsgSetUsername (must match chain ante)

    // Handle the continue button: fetch PoW params, compute PoW, sign relay and relay
    const handleContinue = async event => {
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

        // Validate invite code or referrer
        let codeClean = hasValidInviteFromUrl ? formattedInviteFromUrl : "";
        const usingReferrer = inviteCodeRequired && referrerStatus === "valid" && referrerUsername;
        if (inviteCodeRequired && !usingReferrer) {
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
                setSubmitError(formatError(inviteRes));
                const until = Date.now() + 1000;
                setCooldownUntil(until);
                setTimeout(() => setCooldownUntil(0), 1000);
                return;
            }
        } else if (inviteCodeRequired && usingReferrer) {
            // Re-check referrer availability before submit
            try {
                const precheck = await Api.get('referrals/precheck', {
                    username: referrerUsername
                });
                if (!precheck || !precheck.valid) {
                    setReferrerError(precheck || "referrer_check_failed");
                    setReferrerStatus("invalid");
                    const until = Date.now() + 1000;
                    setCooldownUntil(until);
                    setTimeout(() => setCooldownUntil(0), 1000);
                    return;
                }
            } catch (_) {
                setReferrerError("referrer_check_failed");
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
        try {
            Storage.save('username_pending', usernameFinal);
        } catch (_) { }
        try {
            Storage.save('publicKey_pending', publicKey);
        } catch (_) { }
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
            const submittedReferrer = codeClean ? "" : referrerUsername;
            const result = await tx.createUser(usernameFinal, codeClean, submittedReferrer);
            if (!result || !result.success) {
                const msg = String((result && result.error) || "Submit failed");
                if (/admin insufficient balance/i.test(msg)) {
                    setSubmitError("Your account balance is too low to cover the transaction fee.");
                } else if (/insufficient funds/i.test(msg)) {
                    setSubmitError("Unfortunately the node does not have enough gas available to complete this transaction.");
                } else {
                    setSubmitError(formatError(result));
                }
                const until = Date.now() + 1000;
                setCooldownUntil(until);
                setTimeout(() => setCooldownUntil(0), 1000);
                setSubmitting(false);
                setButtonStatus("idle");
                setStatusStartTime(null);
                try {
                    Storage.remove('username_pending');
                } catch (_) { }
                try {
                    Storage.remove('publicKey_pending');
                } catch (_) { }
                // Do not sign out on initial submit failure; let user retry
                return;
            }

            // Transaction broadcast succeeded (code=0 from BROADCAST_MODE_SYNC).
            // Navigate to welcome and show seed phrase IMMEDIATELY — never gate
            // seed phrase display on indexer confirmation. The account exists on-chain.
            const finalUsername = `Anon-${base}`;
            try {
                Storage.remove('username_pending');
            } catch (_) { }
            try {
                Storage.remove('publicKey_pending');
            } catch (_) { }
            try {
                localStorage.setItem('user_balance', String(localStorage.getItem('user_balance') || '0'));
            } catch (_) { }
            clearReferralAttribution();
            navigate('/welcome', {
                state: {
                    username: finalUsername,
                    seedPhrase
                },
                replace: true
            });
            setCredentials(publicKey, finalUsername, seedPhrase);
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
    // configUpdateTrigger > 0 means the nodeConfigUpdated event fired at least once (fetch finished).
    const configFetchDone = configUpdateTrigger > 0;
    return {
        location,
        nodeConfig,
        registrationEnabled,
        inviteCodeRequired,
        fromRecovery,
        refFromUrl,
        inviteCode,
        setInviteCode,
        usernameInput,
        setUsernameInput,
        submitting,
        buttonStatus,
        submitError,
        setSubmitError,
        cooldownUntil,
        referrerStatus,
        referrerAvailable,
        referrerError,
        handleContinue,
        usernameFinal,
        configFetchDone
    };
}
