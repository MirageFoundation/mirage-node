import React from "react";
import { Helmet } from "react-helmet-async";
import styled from "styled-components";
import AuthPageShell, { AuthStack } from "../components/AuthPageShell.js";
import { ContentGrid, ModernPostFeed } from "../Layout";
import { useSignOut } from "../../../logic/useSignOut";

/**
 * SignOutView — the `/sign_out` route now only runs the sign-out effect.
 *
 * The "Are you sure?" confirmation moved to a `ConfirmDialog` modal triggered
 * from the profile menu (TopBar / MobileBottomNav). Direct navigation to
 * `/sign_out` (or the confirm button) lands here and immediately clears
 * credentials via `useSignOut`, showing a brief "Signing out…" status while
 * the redirect happens.
 */

const StatusBlock = styled.div`
  padding: 0.9rem 0.6rem;
  text-align: center;
  color: ${({ theme }) => theme.colors.subtleText};
  font-size: 0.78rem;
  font-weight: 500;
`;

function SignOutView({ state, setCredentials }) {
  useSignOut({ state, setCredentials });

  return (
    <ContentGrid>
      <Helmet>
        <title>Sign Out | Mirage</title>
      </Helmet>
      <div>
        <ModernPostFeed>
          <AuthPageShell
            showTabs={false}
            eyebrow="Sign out"
            title="Signing you out"
            description="Clearing your session on this device."
          >
            <AuthStack>
              <StatusBlock role="status" aria-live="polite">
                Signing out…
              </StatusBlock>
            </AuthStack>
          </AuthPageShell>
        </ModernPostFeed>
      </div>
    </ContentGrid>
  );
}

export default SignOutView;
