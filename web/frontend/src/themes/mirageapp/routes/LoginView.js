import { Helmet } from "react-helmet-async";
import styled from "styled-components";
import Button from "../components/Button.js";
import seedVault from "../../../utils/SeedVault";
import AuthPageShell, {
  AuthButtonRow,
  AuthErrorMessage,
  AuthHelperText,
  AuthLabel,
  AuthLink,
  AuthLinkRow,
  AuthPanel,
  AuthStack,
  AuthSubtlePanel,
  AuthTextArea,
  AuthTextButton,
} from "../components/AuthPageShell.js";
import { ContentGrid, ModernPostFeed } from "../Layout";
import { useLogin } from "../../../logic/useLogin";

const LabelRow = styled.div`
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
  margin-bottom: 0.4rem;
`;

const WordCount = styled.span`
  display: inline-flex;
  align-items: center;
  padding: 0.12rem 0.45rem;
  border-radius: 999px;
  background: ${({ theme, $isValid }) =>
    $isValid
      ? (theme.name === 'dark' ? 'rgba(52, 199, 89, 0.12)' : 'rgba(52, 199, 89, 0.1)')
      : (theme.name === 'dark' ? 'rgba(255, 255, 255, 0.06)' : 'rgba(0, 0, 0, 0.05)')};
  color: ${({ theme, $isValid }) =>
    $isValid ? theme.colors.voteUp : theme.colors.subtleText};
  font-size: 0.6rem;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
  letter-spacing: 0.01em;
  border: 1px solid ${({ theme, $isValid }) =>
    $isValid
      ? (theme.name === 'dark' ? 'rgba(52, 199, 89, 0.2)' : 'rgba(52, 199, 89, 0.18)')
      : theme.colors.border};
  transition: background 0.15s ease, color 0.15s ease, border-color 0.15s ease;
`;

const VaultRow = styled.div`
  display: flex;
  align-items: center;
  gap: 0.6rem;
`;

const VaultIcon = styled.div`
  width: 1.7rem;
  height: 1.7rem;
  flex: 0 0 auto;
  border-radius: 0.55rem;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: #ffffff;
  font-size: 0.85rem;
  line-height: 1;
`;

const VaultBody = styled.div`
  flex: 1;
  min-width: 0;
`;

const VaultTitle = styled.div`
  color: ${({ theme }) => theme.colors.text};
  font-size: 0.78rem;
  font-weight: 600;
  line-height: 1.25;
`;

const PrimaryButton = styled(Button)`
  border: ${({ theme }) => theme.name === 'dark' ? '0.5px' : '1px'} solid rgba(102, 126, 234, 0.45) !important;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%) !important;
  box-shadow: 0 6px 16px rgba(102, 126, 234, 0.22) !important;

  &:hover:not(:disabled) {
    border-color: rgba(118, 75, 162, 0.75) !important;
    box-shadow: 0 10px 22px rgba(102, 126, 234, 0.28) !important;
    filter: brightness(1.05);
  }
`;

function LoginView({
  state,
  setCredentials,
}) {
  const {
    navigate,
    seedPhrase,
    setSeedPhrase,
    error,
    setError,
    loading,
    handleSubmit,
  } = useLogin({
    state,
    setCredentials,
  });

  const trimmed = (seedPhrase || "").trim();
  const wordCount = trimmed ? trimmed.split(/\s+/).filter(Boolean).length : 0;
  const wordsValid = wordCount === 12;

  return (
    <ContentGrid>
      <Helmet>
        <title>Sign In | Mirage</title>
      </Helmet>
      <div>
        <ModernPostFeed>
          <AuthPageShell
            activeTab="login"
            eyebrow="Welcome back"
            title="Sign in to Mirage"
            description="Enter your 12-word recovery phrase to unlock your account."

            footer={(
              <AuthLinkRow>
                Don&apos;t have an account?
                <AuthLink
                  href="/signup"
                  onClick={(event) => {
                    if (event.button === 0 && !event.metaKey && !event.ctrlKey && !event.shiftKey) {
                      event.preventDefault();
                      navigate("/signup");
                    }
                  }}
                >
                  Create one
                </AuthLink>
              </AuthLinkRow>
            )}
          >
            <AuthStack>
              <AuthPanel as="form" onSubmit={handleSubmit}>
                <LabelRow>
                  <AuthLabel htmlFor="mirage-login-seed" style={{ marginBottom: 0 }}>
                    Recovery phrase
                  </AuthLabel>
                  <WordCount $isValid={wordsValid}>
                    {wordCount}/12 words
                  </WordCount>
                </LabelRow>

                <AuthTextArea
                  id="mirage-login-seed"
                  placeholder="twelve words separated by spaces"
                  value={seedPhrase}
                  onChange={(event) => {
                    setSeedPhrase(event.target.value.toLowerCase());
                    setError("");
                  }}
                  autoCorrect="off"
                  autoCapitalize="off"
                  spellCheck="false"
                  disabled={loading}
                />
                <AuthHelperText>
                  Mirage finds your username automatically once the phrase is verified.
                </AuthHelperText>

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
                </AuthButtonRow>
              </AuthPanel>

              {seedVault.isLocked() ? (
                <AuthSubtlePanel>
                  <VaultRow>
                    <VaultIcon aria-hidden="true">🔒</VaultIcon>
                    <VaultBody>
                      <VaultTitle>Encrypted vault detected</VaultTitle>
                      <AuthHelperText style={{ marginTop: 0 }}>
                        Unlock the vault saved on this device instead.
                      </AuthHelperText>
                    </VaultBody>
                  </VaultRow>
                  <AuthButtonRow>
                    <AuthTextButton
                      type="button"
                      onClick={() => window.dispatchEvent(new CustomEvent("showVaultUnlock"))}
                    >
                      Unlock saved vault
                    </AuthTextButton>
                  </AuthButtonRow>
                </AuthSubtlePanel>
              ) : null}
            </AuthStack>
          </AuthPageShell>
        </ModernPostFeed>
      </div>
    </ContentGrid>
  );
}

export default LoginView;
