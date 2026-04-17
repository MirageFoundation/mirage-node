import React, { useState } from "react";
import { Helmet } from "react-helmet-async";
import { useNavigate } from "react-router-dom";
import styled from "styled-components";
import Button from "../components/Button.js";
import AuthPageShell, {
  AuthButtonRow,
  AuthStack,
} from "../components/AuthPageShell.js";
import { ContentGrid, ModernPostFeed } from "../Layout";
import { useSignOut } from "../../../logic/useSignOut";

const StatusBlock = styled.div`
  padding: 0.9rem 0.6rem;
  text-align: center;
  color: ${({ theme }) => theme.colors.subtleText};
  font-size: 0.78rem;
  font-weight: 500;
`;

function SigningOutEffect({ state, setCredentials }) {
  useSignOut({ state, setCredentials });
  return (
    <AuthStack>
      <StatusBlock role="status" aria-live="polite">
        Signing out…
      </StatusBlock>
    </AuthStack>
  );
}

function SignOutView({ state, setCredentials }) {
  const navigate = useNavigate();
  const [confirmed, setConfirmed] = useState(false);

  const handleCancel = () => {
    if (window.history.length > 1) {
      navigate(-1);
    } else {
      navigate("/");
    }
  };

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
            title={confirmed ? "Signing you out" : "Are you sure you want to logout?"}
            description={
              confirmed
                ? "Clearing your session on this device."
                : "you’ll need your recovery phrase to log back in."
            }
          >
            {confirmed ? (
              <SigningOutEffect state={state} setCredentials={setCredentials} />
            ) : (
              <AuthButtonRow>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  fullWidth
                  mobileFullWidth
                  onClick={handleCancel}
                >
                  Cancel
                </Button>
                <Button
                  type="button"
                  variant="primaryDanger"
                  size="sm"
                  fullWidth
                  mobileFullWidth
                  onClick={() => setConfirmed(true)}
                >
                  Sign out
                </Button>
              </AuthButtonRow>
            )}
          </AuthPageShell>
        </ModernPostFeed>
      </div>
    </ContentGrid>
  );
}

export default SignOutView;
