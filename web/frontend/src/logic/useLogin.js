import { useState, useRef, useEffect } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { deriveKeysFromSeed } from "../utils/CryptoUtils.js";
import { validateMnemonic } from "bip39";
import Api from "../utils/api";
import Storage from "../utils/Storage";
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

  // If user is already signed in, redirect to home
  useEffect(() => {
    if (state.publicKey) {
      navigate('/', {
        replace: true
      });
    }
  }, [state.publicKey, navigate]);
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
    } catch (e) {
      return null;
    }
  };
  const handleLoginWithSeed = async () => {
    setError('');
    setLoading(true);
    try {
      const trimmedSeed = seedPhrase.trim();
      if (!trimmedSeed) {
        if (mountedRef.current) setError('Please enter your recovery phrase');
        if (mountedRef.current) setLoading(false);
        return;
      }
      const normalizedSeed = trimmedSeed.toLowerCase();
      if (trimmedSeed !== normalizedSeed) {
        try {
          console.debug('[Login] normalized recovery phrase to lowercase', {
            wordCount: trimmedSeed.split(/\s+/).filter(Boolean).length
          });
        } catch (_) {}
      }
      if (!validateMnemonic(normalizedSeed)) {
        if (mountedRef.current) setError('Invalid recovery phrase');
        if (mountedRef.current) setLoading(false);
        return;
      }
      const {
        publicKey
      } = deriveKeysFromSeed(normalizedSeed);
      const username = await fetchUsernameFromAddress(publicKey);
      if (!username) {
        // Account not found - redirect to create account with the provided seed
        if (mountedRef.current) setLoading(false);
        navigate('/signup', {
          state: {
            importedSeed: normalizedSeed,
            fromRecovery: true
          },
          replace: true
        });
        return;
      }

      // Dismiss the welcome card for returning users (they already know the app)
      try {
        Storage.save('welcome_card_dismissed_v1', true);
      } catch (_) {}
      setCredentials(publicKey, username, normalizedSeed);
      navigate('/');
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