import { useState, useEffect } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import Storage from "../utils/Storage.js";
import Api from "../utils/api";
import * as tx from "../utils/tx";
import { getMaxUsernameSize, getMinUsernameSize } from "../utils/chainParams";
import { formatError } from "../utils/errorMessages";
export function useChangeUsername({
    state
}) {
    const navigate = useNavigate();
    const location = useLocation();
    const currentUsername = state?.username || Storage.load('username', '');
    const publicKey = state?.publicKey || Storage.load('publicKey', '');
    const [usernameInput, setUsernameInput] = useState("");
    const [submitting, setSubmitting] = useState(false);
    const [buttonStatus, setButtonStatus] = useState("idle");
    const [statusStartTime, setStatusStartTime] = useState(null);
    const [, setElapsedTime] = useState(0);
    const [submitError, setSubmitError] = useState("");
    const [cooldownUntil, setCooldownUntil] = useState(0);
    const [userLevel, setUserLevel] = useState(null);
    const [success, setSuccess] = useState(false);
    useEffect(() => {
        const fetchUserStatus = async () => {
            try {
                const data = await Api.get('get_user_status', {
                    address: publicKey,
                    _cb: Date.now()
                });
                if (data) {
                    setUserLevel(parseInt(data.user_level || 0));
                }
            } catch (e) {
                console.error('Failed to fetch user status:', e);
            }
        };
        if (publicKey) {
            fetchUserStatus();
        }
    }, [publicKey]);

    // Update elapsed time every 100ms when a status is active
    useEffect(() => {
        if (!statusStartTime || buttonStatus === "idle") {
            setElapsedTime(0);
            return;
        }
        const interval = setInterval(() => {
            setElapsedTime((Date.now() - statusStartTime) / 1000);
        }, 100);
        return () => clearInterval(interval);
    }, [statusStartTime, buttonStatus]);

    // Blur focused element when submitting to remove blinking cursor
    useEffect(() => {
        if (submitting && document.activeElement && document.activeElement.blur) {
            document.activeElement.blur();
        }
    }, [submitting]);
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
            const available = !!(data && !data.exists);
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
    const handleSubmit = async event => {
        event.preventDefault();
        if (Date.now() < cooldownUntil) return;
        if (!publicKey) return;
        const inputPart = (usernameInput || "").trim();
        if (!inputPart) {
            setSubmitError("Username cannot be empty");
            return;
        }
        const isFreeUser = userLevel !== null && userLevel < 1;
        const newUsername = isFreeUser ? "Anon-" + inputPart : inputPart;

        // Use defaults if params not cached yet
        const minSize = getMinUsernameSize() ?? 5;
        const maxSize = getMaxUsernameSize() ?? 30;
        if (newUsername.length < minSize) {
            setSubmitError(`Username too short. Minimum ${minSize} characters required.`);
            return;
        }
        if (newUsername.length > maxSize) {
            setSubmitError(`Username too long. Maximum ${maxSize} characters allowed.`);
            return;
        }
        if (userLevel === null) {
            setSubmitError("Loading account information...");
            return;
        }
        if (newUsername === currentUsername) {
            setSubmitError("New username is the same as current username");
            return;
        }
        setSubmitError("");
        setSubmitting(true);
        setButtonStatus("checking");
        setStatusStartTime(Date.now());
        // Allow React to render the status update before starting the async operation
        await new Promise(r => setTimeout(r, 50));
        const availRes = await checkUsernameAvailable(newUsername);
        if (!availRes || availRes.error) {
            setSubmitError("Cannot check username: server unavailable");
            const until = Date.now() + 1000;
            setCooldownUntil(until);
            setTimeout(() => setCooldownUntil(0), 1000);
            setSubmitting(false);
            setButtonStatus("idle");
            setStatusStartTime(null);
            return;
        }
        if (!availRes.available) {
            setSubmitError("Username already taken");
            const until = Date.now() + 1000;
            setCooldownUntil(until);
            setTimeout(() => setCooldownUntil(0), 1000);
            setSubmitting(false);
            setButtonStatus("idle");
            setStatusStartTime(null);
            return;
        }

        // Stage 1: Preparing (PoW + transaction creation)
        setButtonStatus("preparing");
        setStatusStartTime(Date.now());
        await new Promise(r => setTimeout(r, 50)); // Let React render
        try {
            const result = await tx.setUsername(newUsername);
            if (!result || !result.success) {
                const msg = String((result && result.error) || "Submit failed");
                if (/admin insufficient balance/i.test(msg)) {
                    setSubmitError("Your account balance is too low to cover the transaction fee.");
                } else if (/insufficient funds/i.test(msg)) {
                    setSubmitError("Insufficient funds to complete this transaction.");
                } else {
                    setSubmitError(formatError(result));
                }
                const until = Date.now() + 1000;
                setCooldownUntil(until);
                setTimeout(() => setCooldownUntil(0), 1000);
                setSubmitting(false);
                setButtonStatus("idle");
                setStatusStartTime(null);
                return;
            }
            try {
                const txHash = result && result.tx_hash ? String(result.tx_hash).toLowerCase() : "";
                if (!txHash) throw new Error("missing tx hash");

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
                const pollResult = await tx.pollTxStatus(txHash);
                if (!pollResult) throw new Error('confirmation timeout');
                if (!pollResult.success) {
                    throw new Error(pollResult.error_details?.message || 'transaction rejected');
                }
                Storage.save('username', newUsername);
                setSuccess(true);
                setButtonStatus("idle");
                setStatusStartTime(null);
                setTimeout(() => {
                    navigate('/profile');
                    window.location.reload();
                }, 3000);
            } catch (e) {
                setSubmitError(String(e && e.message ? e.message : 'Failed to confirm transaction'));
                setSubmitting(false);
                setButtonStatus("idle");
                setStatusStartTime(null);
                return;
            }
        } catch (e) {
            setSubmitError(String(e?.message || e || "Submit failed"));
            setSubmitting(false);
            setButtonStatus("idle");
            setStatusStartTime(null);
        }
    };
    const canChangeName = userLevel !== null && userLevel >= 1;
    return {
        location,
        currentUsername,
        usernameInput,
        setUsernameInput,
        submitting,
        buttonStatus,
        submitError,
        setSubmitError,
        cooldownUntil,
        userLevel,
        success,
        handleSubmit,
        canChangeName
    };
}