import { useState, useEffect } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { trackEvent } from "../utils/analytics";
export function useWelcome({
  state
}) {
  const navigate = useNavigate();
  const location = useLocation();
  const [copied, setCopied] = useState(false);
  const {
    username,
    seedPhrase
  } = location.state || {};
  useEffect(() => {
    if (!username || !seedPhrase) {
      navigate('/');
    }
  }, [username, seedPhrase, navigate]);
  useEffect(() => {
    if (username && seedPhrase) trackEvent("recovery_phrase_viewed");
  }, [username, seedPhrase]);
  return {
    navigate,
    location,
    copied,
    setCopied,
    username,
    seedPhrase
  };
}
