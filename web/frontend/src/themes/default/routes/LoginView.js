import { Helmet } from "react-helmet-async";
import styled from "styled-components";
import Button from "../components/Button.js";
import seedVault from "../../../utils/SeedVault";
import AuthPageShell, {
  AuthButtonRow,
  AuthErrorMessage,
  AuthFieldRow,
  AuthHelperText,
  AuthLabel,
  AuthLabelHint,
  AuthLabelRow,
  AuthLink,
  AuthLinkRow,
  AuthStack,
  AuthTextArea,
  AuthTextButton,
} from "../components/AuthPageShell.js";
import { ContentGrid, ModernPostFeed } from "../Layout";
import { useLogin } from "../../../logic/useLogin";

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

function LoginView({ state, setCredentials }) {
  const {
    navigate,
    seedPhrase,
    setSeedPhrase,
    error,
    setError,
    loading,
    handleSubmit,
  } = useLogin({ state, setCredentials });

  const trimmed = (seedPhrase || "").trim();
  const wordCount = trimmed ? trimmed.split(/\s+/).filter(Boolean).length : 0;
  const wordsValid = wordCount === 12;
  const showVault = seedVault.isLocked();

  return (
    <ContentGrid>
      <Helmet>
        <title>Sign in | Mirage</title>
      </Helmet>
      <div>
        <ModernPostFeed>
          <AuthPageShell
            title="Sign in"
            description="Sign in to your existing Mirage account with your 12-word recovery phrase (each word is separated by a space)."
            footer={(
              <AuthLinkRow>
                New to Mirage?
                <AuthLink
                  href="/signup"
                  onClick={(event) => {
                    if (event.button === 0 && !event.metaKey && !event.ctrlKey && !event.shiftKey) {
                      event.preventDefault();
                      navigate("/signup");
                    }
                  }}
                >
                  Create an account
                </AuthLink>
              </AuthLinkRow>
            )}
          >
            <AuthStack as="form" onSubmit={handleSubmit}>
              <AuthFieldRow>
                <AuthLabelRow>
                  <AuthLabel htmlFor="mirage-login-seed">Recovery phrase</AuthLabel>
                  <AuthLabelHint aria-live="polite">
                    {wordCount}/12 {wordsValid ? "✓" : "words"}
                  </AuthLabelHint>
                </AuthLabelRow>
                <AuthTextArea
                  id="mirage-login-seed"
                  placeholder="Enter your 12-word recovery phrase"
                  value={seedPhrase}
                  onChange={(event) => {
                    setSeedPhrase(event.target.value.toLowerCase());
                    setError("");
                  }}
                  autoCorrect="off"
                  autoCapitalize="off"
                  spellCheck="false"
                  autoComplete="off"
                  data-1p-ignore="true"
                  data-lpignore="true"
                  data-form-type="other"
                  name="mirage-recovery-phrase"
                  disabled={loading}
                />
                <AuthHelperText>
                  Enter your recovery phrase privately. It stays on this device and is never sent to Mirage servers as plaintext login.
                </AuthHelperText>
              </AuthFieldRow>

              {error ? <AuthErrorMessage role="alert">{error}</AuthErrorMessage> : null}

              <AuthButtonRow>
                <PrimaryButton
                  type="submit"
                  disabled={loading}
                  fullWidth
                  mobileFullWidth
                  size="sm"
                  loading={loading}
                >
                  {loading ? "Signing in…" : "Sign in"}
                </PrimaryButton>
                {showVault ? (
                  <AuthTextButton
                    type="button"
                    onClick={() => window.dispatchEvent(new CustomEvent("showVaultUnlock"))}
                  >
                    Unlock saved vault on this device
                  </AuthTextButton>
                ) : null}
              </AuthButtonRow>
            </AuthStack>
          </AuthPageShell>
        </ModernPostFeed>
      </div>
    </ContentGrid>
  );
}

export default LoginView;
