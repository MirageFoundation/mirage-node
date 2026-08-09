import React from "react";
import { useNavigate } from "react-router-dom";
import { resetClientSession } from "../utils/sessionLifecycle";

/**
 * Sign-out route effect. Confirmation happens before navigating here
 * (TopBar / MobileBottomNav ConfirmDialog). This hook clears the session.
 */
export function useSignOut({
  state: _state,
  setCredentials
}) {
  let navigate = useNavigate();
  React.useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        console.debug('[SignOut] session-reset-start');
      } catch (_) { /* noop */ }
      await resetClientSession({ reason: 'sign_out', preserveAnalytics: true, clearVault: true });
      if (cancelled) return;
      setCredentials("", "", "");
      navigate("/");
    })();
    return () => { cancelled = true; };
  }, [navigate, setCredentials]);
  return {};
}
