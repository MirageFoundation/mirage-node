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
      // hardReset so sessionStorage goes too — feed_order_*, feed_scroll_*,
      // mirage_came_from_feed and the pending seen-post batch all live there and
      // would otherwise be inherited by the next account in this tab.
      await resetClientSession({ reason: 'sign_out', clearVault: true, hardReset: true });
      if (cancelled) return;
      setCredentials("", "", "");
      navigate("/");
    })();
    return () => { cancelled = true; };
  }, [navigate, setCredentials]);
  return {};
}
