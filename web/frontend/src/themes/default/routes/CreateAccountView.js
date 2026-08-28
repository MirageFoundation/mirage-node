import { Helmet } from "react-helmet-async";
import styled from "styled-components";
import Button from "../components/Button.js";
import AuthPageShell, {
  AuthButtonRow,
  AuthErrorMessage,
  AuthFieldRow,
  AuthHelperText,
  AuthLabel,
  AuthLink,
  AuthLinkRow,
  AuthStack,
  AuthSubtlePanel,
} from "../components/AuthPageShell.js";
import { ContentGrid, ModernPostFeed } from "../Layout";
import { getMaxInputLength } from "../../../utils/chainParams";
import { useCreateAccount } from "../../../logic/useCreateAccount";

const StatusLine = styled.div`
  color: ${({ theme }) => theme.colors.text};
  font-size: 0.72rem;
  line-height: 1.5;
`;

/* Centered, non-wrapping status line used by the "Signup unavailable"
 * error panel — keeps the long "Mirage could not load…" message on one
 * line on larger screens (the shell widens via `wide`) while still
 * wrapping gracefully below the 600px breakpoint. */
const CenteredStatusLine = styled(StatusLine)`
  text-align: center;

  @media (min-width: 601px) {
    white-space: nowrap;
  }
`;

const HandleField = styled.div`
  display: flex;
  align-items: stretch;
  width: 100%;
  box-sizing: border-box;
  border: 1px solid ${({ theme }) => theme.colors.border};
  border-radius: 0.55rem;
  background: ${({ theme }) => theme.colors.bg};
  overflow: hidden;
  transition: border-color 0.15s ease;

  &:hover {
    border-color: ${({ theme }) => theme.colors.borderStrong};
  }

  &:focus-within {
    border-color: ${({ theme }) => theme.colors.borderStrong};
  }
`;

const HandlePrefix = styled.span`
  display: inline-flex;
  align-items: center;
  padding: 0 0 0 0.7rem;
  color: ${({ theme, $active }) => ($active ? theme.colors.text : theme.colors.subtleText)};
  font-size: 0.75rem;
  font-weight: 500;
  user-select: none;
`;

const HandleInput = styled.input`
  flex: 1;
  min-width: 0;
  border: 0;
  background: transparent;
  color: ${({ theme }) => theme.colors.text};
  padding: 0.55rem 0.7rem 0.55rem 0;
  font: inherit;
  font-size: 0.75rem;
  font-weight: 500;
  line-height: 1.4;
  outline: none;

  &::placeholder {
    color: ${({ theme }) => theme.colors.subtleText};
  }

  &:disabled {
    opacity: 0.6;
    cursor: not-allowed;
  }
`;

const PrimaryButton = styled(Button)`
  border: none !important;
  background: ${({ theme }) => theme.colors.followBtnBg} !important;
  color: #ffffff !important;
  box-shadow: none !important;
  transition: background 0.15s ease !important;

  &:hover:not(:disabled) {
    background: ${({ theme }) => theme.colors.followBtnBgHover} !important;
  }

  &:disabled {
    opacity: 0.55;
  }
`;

function CreateAccountView({ state, setCredentials }) {
  const {
    nodeConfig,
    registrationEnabled,
    fromRecovery,
    usernameInput,
    setUsernameInput,
    submitting,
    buttonStatus,
    submitError,
    setSubmitError,
    cooldownUntil,
    handleContinue,
    usernameFinal,
    configFetchDone,
  } = useCreateAccount({ state, setCredentials });

  const pageTitle = fromRecovery ? "Finish your account" : "Create your account";
  const pageDescription = fromRecovery
    ? "No account exists for that recovery phrase yet. Pick a username to claim it."
    : "Free accounts are prefixed with Anon- to prevent spam. You can upgrade with MIRAGE later to drop the prefix and unlock premium features.";

  const continueDisabled =
    submitting
    || Date.now() < cooldownUntil
    || usernameFinal.trim() === "";

  const footer = (
    <AuthLinkRow>
      Already have an account?
      <AuthLink href="/login">Sign in</AuthLink>
    </AuthLinkRow>
  );

  const renderUnavailable = (title, body) => (
    <ContentGrid>
      <Helmet>
        <title>Create account | Mirage</title>
      </Helmet>
      <div>
        <ModernPostFeed>
          <AuthPageShell title={title} description={body} footer={footer} wide>
            <AuthSubtlePanel>
              <CenteredStatusLine>{body}</CenteredStatusLine>
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

  const buttonLabel = buttonStatus === "preparing"
    ? "Preparing…"
    : buttonStatus === "submitting"
      ? "Submitting…"
      : buttonStatus === "verifying"
        ? "Verifying…"
        : "Create account";

  return (
    <ContentGrid>
      <Helmet>
        <title>Create account | Mirage</title>
      </Helmet>
      <div>
        <ModernPostFeed>
          <AuthPageShell
            title={pageTitle}
            description={pageDescription}
            footer={footer}
          >
            <AuthStack as="form" onSubmit={handleContinue}>
              <AuthFieldRow>
                <AuthLabel htmlFor="display-name-entry">Username</AuthLabel>
                <HandleField>
                  <HandlePrefix aria-hidden="true" $active={usernameInput.length > 0}>Anon-</HandlePrefix>
                  <HandleInput
                    id="display-name-entry"
                    placeholder="name"
                    value={usernameInput}
                    onChange={(event) => {
                      const raw = event.target.value;
                      const cleaned = raw.replace(/[^A-Za-z0-9-]/g, "");
                      const maxLen = getMaxInputLength(true);
                      setUsernameInput(cleaned.slice(0, maxLen ?? 100));
                      setSubmitError("");
                    }}
                    onPaste={(event) => event.preventDefault()}
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
                </HandleField>
                <AuthHelperText>
                  Letters, numbers, and hyphens only.
                </AuthHelperText>
              </AuthFieldRow>

              {submitError ? (
                <AuthErrorMessage role="alert">{submitError}</AuthErrorMessage>
              ) : null}

              <AuthButtonRow>
                <PrimaryButton
                  type="submit"
                  disabled={continueDisabled}
                  fullWidth
                  mobileFullWidth
                  size="sm"
                  loading={submitting}
                >
                  {buttonLabel}
                </PrimaryButton>
              </AuthButtonRow>
            </AuthStack>
          </AuthPageShell>
        </ModernPostFeed>
      </div>
    </ContentGrid>
  );
}

export default CreateAccountView;
