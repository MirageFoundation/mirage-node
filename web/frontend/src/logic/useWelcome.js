import { useState, useEffect } from "react";
import { useNavigate, useLocation } from "react-router-dom";
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
  return {
    navigate,
    location,
    copied,
    setCopied,
    username,
    seedPhrase
  };
}