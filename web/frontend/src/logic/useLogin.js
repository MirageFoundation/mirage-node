import { useState, useRef, useEffect, useCallback } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { deriveKeysFromSeed, requireValidMnemonic } from "../utils/CryptoUtils.js";
import Api from "../utils/api";
import { createHandoff } from "../utils/onboardingSession";
import { readReturnTo } from "../utils/returnTo";
export function useLogin({
    state,
    setCredentials
}) {
    const navigate = useNavigate();
    const location = useLocation();
    const mountedRef = useRef(true);
    const [seedPhrase, setSeedPhrase] = useState('');
    const [error, setError] = useState('');
    const [loading, setLoading] = useState(false);
    const afterLoginPath = useCallback(() => readReturnTo(location.search) || '/', [location.search]);

    // If user is already signed in, honor ?next= then fall back to home
    useEffect(() => {
        if (state.publicKey) {
            const next = afterLoginPath();
            console.debug('[Login] already signed in; redirect', { next });
            navigate(next, {
                replace: true
            });
        }
    }, [state.publicKey, navigate, afterLoginPath]);
    useEffect(() => {
        mountedRef.current = true;
        return () => {
            mountedRef.current = false;
        };
    }, []);
    const fetchUsernameFromAddress = async address => {
        try {
            const data = await Api.get('get_username_from_address', {
                address
            });
            return data?.username || null;
        } catch (_e) {
            return null;
        }
    };
    const handleLoginWithSeed = async () => {
        setError('');
        setLoading(true);
        try {
            let normalizedSeed;
            try {
                normalizedSeed = requireValidMnemonic(seedPhrase);
            } catch (e) {
                if (mountedRef.current) setError(String(e?.message || 'Invalid recovery phrase'));
                if (mountedRef.current) setLoading(false);
                return;
            }
            try {
                console.debug('[Login] validated recovery phrase', {
                    wordCount: normalizedSeed.split(' ').length
                });
            } catch (_) { }
            const {
                publicKey
            } = deriveKeysFromSeed(normalizedSeed);
            const username = await fetchUsernameFromAddress(publicKey);
            if (!username) {
                // Account not found — hand off seed in memory (never via location.state)
                if (mountedRef.current) setLoading(false);
                const { id } = createHandoff({
                    purpose: 'import',
                    seed: normalizedSeed,
                    owner: publicKey,
                });
                navigate('/signup', {
                    state: {
                        handoffId: id,
                        fromRecovery: true
                    },
                    replace: true
                });
                return;
            }

            setCredentials(publicKey, username, normalizedSeed);
            const next = afterLoginPath();
            console.debug('[Login] signed in; redirect', { next });
            navigate(next, { replace: true });
        } catch (e) {
            if (mountedRef.current) setError(String(e?.message || e || 'Login failed'));
        } finally {
            if (mountedRef.current) setLoading(false);
        }
    };
    const handleSubmit = async e => {
        e.preventDefault();
        await handleLoginWithSeed();
    };
    return {
        navigate,
        location,
        seedPhrase,
        setSeedPhrase,
        error,
        setError,
        loading,
        handleSubmit
    };
}
