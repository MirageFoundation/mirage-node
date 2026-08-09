import { useState, useEffect } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { peekHandoff, clearHandoff } from "../utils/onboardingSession";

export function useWelcome({
  state: _state
}) {
  const navigate = useNavigate();
  const location = useLocation();
  const [copied, setCopied] = useState(false);
  const username = location.state?.username || '';
  const handoffId = location.state?.handoffId || null;
  const seedPhrase = (() => {
    if (!handoffId) return '';
    const entry = peekHandoff(handoffId, 'welcome');
    return entry?.seed || '';
  })();

  useEffect(() => {
    if (!username || !seedPhrase) {
      navigate('/');
    }
  }, [username, seedPhrase, navigate]);

  useEffect(() => {
    return () => {
      if (handoffId) clearHandoff(handoffId);
    };
  }, [handoffId]);

  return {
    navigate,
    location,
    copied,
    setCopied,
    username,
    seedPhrase
  };
}
