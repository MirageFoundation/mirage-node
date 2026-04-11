import { Helmet } from "react-helmet-async";
import styled from "styled-components";
import Button from "../components/Button.js";
import AuthPageShell, {
  AuthButtonRow,
  AuthErrorMessage,
  AuthHelperText,
  AuthInlineBadge,
  AuthInput,
  AuthLabel,
  AuthLink,
  AuthLinkRow,
  AuthPanel,
  AuthStack,
  AuthSubtlePanel,
} from "../components/AuthPageShell.js";
import MobileHeader from "../components/MobileHeader.js";
import { ContentGrid, ModernPostFeed } from "../Layout";
import { getMaxInputLength } from "../../../utils/chainParams";
import { formatError } from "../../../utils/errorMessages";
import { useCreateAccount } from "../../../logic/useCreateAccount";

const PanelTitle = styled.h2`
  margin: 0 0 0.4rem;
  color: ${({ theme }) => theme.colors.text};
  font-size: 0.82rem;
  font-weight: 600;
  line-height: 1.2;
`;

const StatusLine = styled.div`
  color: ${({ theme }) => theme.colors.text};
  font-size: 0.78rem;
  line-height: 1.5;
`;

const FeatureGrid = styled.div`
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0.45rem;
  margin-top: 0.75rem;

  @media (max-width: 600px) {
    grid-template-columns: 1fr;
  }
`;

const FeatureTile = styled.div`
  display: flex;
  align-items: flex-start;
  gap: 0.55rem;
  padding: 0.6rem 0.65rem;
  border-radius: 0.75rem;
  border: 1px solid ${({ theme }) => theme.colors.border};
  background: ${({ theme }) => theme.name === "light" ? "#FFFFFF" : "rgb(25, 28, 31)"};
`;

const FeatureIcon = styled.div`
  width: 1.55rem;
  height: 1.55rem;
  flex: 0 0 auto;
  border-radius: 0.55rem;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 0.85rem;
  line-height: 1;
  background: ${({ $tone }) =>
    $tone === "purple"
      ? "rgba(102, 126, 234, 0.18)"
      : $tone === "green"
        ? "rgba(16, 185, 129, 0.18)"
        : "rgba(245, 158, 11, 0.18)"};
  color: ${({ $tone }) =>
    $tone === "purple" ? "#667eea" : $tone === "green" ? "#10b981" : "#f59e0b"};
`;

const FeatureBody = styled.div`
  min-width: 0;
`;

const FeatureTitle = styled.div`
  color: ${({ theme }) => theme.colors.text};
  font-size: 0.74rem;
  font-weight: 600;
  line-height: 1.2;
`;

const FeatureDesc = styled.div`
  margin-top: 0.18rem;
  color: ${({ theme }) => theme.colors.subtleText};
  font-size: 0.66rem;
  line-height: 1.4;
`;

const PreviewCard = styled.div`
  margin-top: 0.65rem;
  padding: 0.65rem 0.78rem;
  border-radius: 0.75rem;
  border: 1px dashed ${({ theme }) => theme.colors.border};
  background: ${({ theme }) => theme.name === "light" ? "rgb(243, 243, 243)" : "rgb(36, 39, 45)"};
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
`;

const PreviewLeft = styled.div`
  min-width: 0;
`;

const PreviewLabel = styled.div`
  color: ${({ theme }) => theme.colors.subtleText};
  font-size: 0.6rem;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  font-weight: 600;
`;

const PreviewValue = styled.div`
  margin-top: 0.2rem;
  color: ${({ theme }) => theme.colors.text};
  font-size: 0.86rem;
  font-weight: 600;
  word-break: break-word;
  font-family: "SFMono-Regular", Menlo, Monaco, Consolas, "Liberation Mono", monospace;
`;

const PreviewBadge = styled.span`
  flex: 0 0 auto;
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  padding: 0.22rem 0.45rem;
  border-radius: 999px;
  background: rgba(16, 185, 129, 0.16);
  color: #10b981;
  font-size: 0.6rem;
  font-weight: 600;

  &::before {
    content: "";
    width: 0.32rem;
    height: 0.32rem;
    border-radius: 999px;
    background: currentColor;
  }
`;

const PrimaryButton = styled(Button)`
  border: 1px solid rgba(102, 126, 234, 0.45) !important;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%) !important;
  box-shadow: 0 6px 16px rgba(102, 126, 234, 0.22) !important;

  &:hover:not(:disabled) {
    border-color: rgba(118, 75, 162, 0.75) !important;
    box-shadow: 0 10px 22px rgba(102, 126, 234, 0.28) !important;
    filter: brightness(1.05);
  }
`;

function CreateAccountView({
  state,
  setCredentials,
}) {
  const {
    nodeConfig,
    registrationEnabled,
    inviteCodeRequired,
    fromRecovery,
    refFromUrl,
    inviteCode,
    setInviteCode,
    usernameInput,
    setUsernameInput,
    submitting,
    buttonStatus,
    submitError,
    setSubmitError,
    cooldownUntil,
    referrerStatus,
    referrerAvailable,
    referrerError,
    handleContinue,
    usernameFinal,
    configFetchDone,
  } = useCreateAccount({
    state,
    setCredentials,
  });

  const pageTitle = fromRecovery ? "Finish setting up your account" : "Create your Mirage account";
  const pageDescription = fromRecovery
    ? "We didn't find an account for that recovery phrase. Pick a username to create one now."
    : "Pick a username — Mirage handles everything else on-chain.";

  const continueDisabled =
    submitting || Date.now() < cooldownUntil || usernameFinal.trim() === "" || referrerStatus === "checking";

  const footer = (
    <AuthLinkRow>
      Already have an account?
      <AuthLink href="/login">Sign in</AuthLink>
    </AuthLinkRow>
  );

  const renderUnavailable = (title, body) => (
    <ContentGrid>
      <Helmet>
        <title>Create Account | Mirage</title>
      </Helmet>
      <div>
        <ModernPostFeed>
          <MobileHeader />
          <AuthPageShell
            activeTab="create"
            eyebrow="Mirage onboarding"
            title={title}
            description={body}
            icon="⚠️"
            footer={footer}
          >
            <AuthSubtlePanel>
              <StatusLine>{body}</StatusLine>
            </AuthSubtlePanel>
          </AuthPageShell>
        </ModernPostFeed>
      </div>
    </ContentGrid>
  );

  if (!nodeConfig) {
    return renderUnavailable(
      configFetchDone ? "Signup unavailable" : "Loading",
      configFetchDone
        ? "Mirage could not load this node's signup settings. Refresh and try again."
        : "Checking whether signup is available on this node…",
    );
  }

  if (!registrationEnabled) {
    return renderUnavailable(
      "Signup unavailable",
      "This node is not accepting new accounts right now.",
    );
  }

  return (
    <ContentGrid>
      <Helmet>
        <title>Create Account | Mirage</title>
      </Helmet>
      <div>
        <ModernPostFeed>
          <MobileHeader />
          <AuthPageShell
            activeTab="create"
            eyebrow={fromRecovery ? "Recovery setup" : "Join Mirage"}
            title={pageTitle}
            description={pageDescription}
            icon="✨"
            footer={footer}
          >
            <AuthStack as="form" onSubmit={handleContinue}>
              {fromRecovery ? (
                <AuthSubtlePanel>
                  <PanelTitle>Recovery phrase ready</PanelTitle>
                  <StatusLine>
                    No on-chain account exists for that phrase yet — create a new one to claim it.
                  </StatusLine>
                </AuthSubtlePanel>
              ) : (
                <FeatureGrid>
                  <FeatureTile>
                    <FeatureIcon $tone="purple" aria-hidden="true">⛓</FeatureIcon>
                    <FeatureBody>
                      <FeatureTitle>On-chain identity</FeatureTitle>
                      <FeatureDesc>Your account lives on the Mirage blockchain.</FeatureDesc>
                    </FeatureBody>
                  </FeatureTile>
                  <FeatureTile>
                    <FeatureIcon $tone="green" aria-hidden="true">🛡</FeatureIcon>
                    <FeatureBody>
                      <FeatureTitle>Self-custody</FeatureTitle>
                      <FeatureDesc>You control the keys — no resets needed.</FeatureDesc>
                    </FeatureBody>
                  </FeatureTile>
                </FeatureGrid>
              )}

              {inviteCodeRequired ? (
                referrerStatus === "valid" ? (
                  <AuthSubtlePanel>
                    <PanelTitle>Invite ready</PanelTitle>
                    <StatusLine>
                      Referral from <strong>@{refFromUrl}</strong> is active.
                    </StatusLine>
                    {referrerAvailable > 0 ? (
                      <AuthHelperText>
                        {referrerAvailable} referral {referrerAvailable === 1 ? "code" : "codes"} left.
                      </AuthHelperText>
                    ) : null}
                  </AuthSubtlePanel>
                ) : referrerStatus === "checking" ? (
                  <AuthSubtlePanel>
                    <PanelTitle>Checking invite</PanelTitle>
                    <StatusLine>Validating referral link…</StatusLine>
                  </AuthSubtlePanel>
                ) : referrerStatus === "invalid" && refFromUrl ? (
                  <AuthSubtlePanel>
                    <PanelTitle>Referral unavailable</PanelTitle>
                    <AuthErrorMessage role="alert" style={{ marginTop: 0 }}>
                      {formatError(referrerError)}
                    </AuthErrorMessage>
                    <AuthHelperText>
                      Have an invite code? <AuthLink href="/signup">Enter it manually</AuthLink>
                    </AuthHelperText>
                  </AuthSubtlePanel>
                ) : (
                  <AuthPanel>
                    <PanelTitle>Invite code</PanelTitle>
                    <AuthLabel htmlFor="invite-code-entry">Enter your invite code</AuthLabel>
                    <AuthInput
                      id="invite-code-entry"
                      placeholder="XXXX-XXXX"
                      value={inviteCode}
                      onChange={(event) => {
                        const raw = event.target.value.toUpperCase();
                        const alphanumOnly = raw.replace(/[^A-Z0-9]/g, "");
                        const limited = alphanumOnly.slice(0, 8);
                        const formatted = limited.length > 4 ? `${limited.slice(0, 4)}-${limited.slice(4)}` : limited;
                        setInviteCode(formatted);
                        setSubmitError("");
                      }}
                      maxLength={9}
                      name="invite-code-entry"
                      autoComplete="one-time-code"
                      autoCorrect="off"
                      autoCapitalize="characters"
                      spellCheck="false"
                      data-lpignore="true"
                      data-1p-ignore="true"
                      data-bwignore="true"
                      data-form-type="other"
                    />
                  </AuthPanel>
                )
              ) : null}

              {!(referrerStatus === "invalid" && refFromUrl) ? (
                <AuthPanel>
                  <AuthLabel htmlFor="display-name-entry">Choose your username</AuthLabel>
                  <AuthInput
                    id="display-name-entry"
                    placeholder="your-name"
                    value={usernameInput}
                    onChange={(event) => {
                      const raw = event.target.value;
                      const cleaned = raw.replace(/[^A-Za-z0-9-]/g, "");
                      const maxLen = getMaxInputLength(true);
                      setUsernameInput(cleaned.slice(0, maxLen ?? 100));
                      setSubmitError("");
                    }}
                    onPaste={(event) => {
                      event.preventDefault();
                    }}
                    maxLength={getMaxInputLength(true) || 100}
                    name="display-name-entry"
                    autoComplete="off"
                    autoCorrect="off"
                    autoCapitalize="off"
                    spellCheck="false"
                    data-lpignore="true"
                    data-1p-ignore="true"
                    data-bwignore="true"
                    data-form-type="other"
                  />
                  <AuthHelperText>
                    Letters, numbers, and hyphens. Free accounts get the <strong>Anon-</strong> prefix.
                  </AuthHelperText>

                  <PreviewCard>
                    <PreviewLeft>
                      <PreviewLabel>Your handle</PreviewLabel>
                      <PreviewValue>{`Anon-${usernameFinal || "your-name"}`}</PreviewValue>
                    </PreviewLeft>
                    {usernameFinal ? <PreviewBadge>Looks good</PreviewBadge> : <AuthInlineBadge>Preview</AuthInlineBadge>}
                  </PreviewCard>

                  {submitError ? <AuthErrorMessage role="alert">{submitError}</AuthErrorMessage> : null}

                  <AuthButtonRow>
                    <PrimaryButton
                      type="submit"
                      disabled={continueDisabled}
                      fullWidth
                      mobileFullWidth
                      size="sm"
                      loading={submitting}
                    >
                      {buttonStatus === "preparing"
                        ? "Preparing…"
                        : buttonStatus === "submitting"
                          ? "Submitting…"
                          : buttonStatus === "verifying"
                            ? "Verifying…"
                            : "Continue"}
                    </PrimaryButton>
                  </AuthButtonRow>
                </AuthPanel>
              ) : null}
            </AuthStack>
          </AuthPageShell>
        </ModernPostFeed>
      </div>
    </ContentGrid>
  );
}

export default CreateAccountView;
