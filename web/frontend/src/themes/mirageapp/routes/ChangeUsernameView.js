import { Helmet } from "react-helmet-async";
import styled from "styled-components";
import Button from "../components/Button.js";
import { Link } from "react-router-dom";
import {
  AuthButtonRow,
  AuthErrorMessage,
  AuthHelperText,
  AuthLabel,
  AuthPanel,
  AuthStack,
  AuthSubtlePanel,
} from "../components/AuthPageShell.js";
import { ContentGrid, ModernPostFeed } from "../Layout";
import { getMaxInputLength } from "../../../utils/chainParams";
import { useChangeUsername } from "../../../logic/useChangeUsername";

const BlockingOverlay = styled.div`
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: transparent;
  z-index: 9999;
  cursor: wait;
`;

const HeaderRow = styled.div`
  display: flex;
  align-items: center;
  justify-content: flex-start;
  gap: 0.75rem;
  padding: 0.5rem 1rem;
`;

const HeaderTitle = styled.div`
  color: ${({ theme }) => theme.colors.text};
  font-size: 1.1rem;
  font-weight: 700;
  letter-spacing: -0.01em;
`;

const Divider = styled.div`
  border-bottom: 1px solid ${({ theme }) => theme.colors.border};
  width: 100%;
`;

const PageWrapper = styled.div`
  width: 100%;
  max-width: 28rem;
  margin: 0 auto;
  padding: 1.2rem 0.85rem 1.6rem;
  box-sizing: border-box;
  text-align: center;

  @media (max-width: 600px) {
    padding: 0.8rem 0.7rem 1.2rem;
  }
`;

const PageTitle = styled.h2`
  margin: 0 0 0.2rem;
  color: ${({ theme }) => theme.colors.text};
  font-size: 1.18rem;
  line-height: 1.15;
  letter-spacing: -0.02em;
  font-weight: 600;
`;

const PageDescription = styled.p`
  margin: 0 0 0.85rem;
  color: ${({ theme }) => theme.colors.subtleText};
  font-size: 0.78rem;
  line-height: 1.5;
`;

const InputRow = styled.div`
  display: flex;
  align-items: center;
  border: 1px solid ${({ theme }) => theme.colors.border};
  border-radius: 10px;
  background: ${({ theme }) => theme.colors.bg};
  overflow: hidden;
  transition: border-color 0.12s ease, background 0.12s ease;
  opacity: ${({ $disabled }) => ($disabled ? 0.55 : 1)};
  pointer-events: ${({ $disabled }) => ($disabled ? "none" : "auto")};

  &:hover {
    border-color: ${({ theme }) => theme.colors.borderStrong};
  }

  &:focus-within {
    border-color: ${({ theme }) => theme.colors.borderStrong};
  }
`;

const InputPrefix = styled.span`
  padding: 0.66rem 0 0.66rem 0.78rem;
  color: ${({ theme }) => theme.colors.subtleText};
  font-size: 0.8rem;
  font-weight: 600;
  line-height: 1.4;
  user-select: none;
  white-space: nowrap;
`;

const InlineInput = styled.input`
  border: none;
  flex: 1;
  min-width: 0;
  width: 100%;
  background: transparent;
  color: ${({ theme }) => theme.colors.text};
  font: inherit;
  font-size: 0.8rem;
  line-height: 1.4;
  padding: 0.66rem 0.78rem;
  padding-left: ${({ $hasPrefix }) => ($hasPrefix ? "0.15rem" : "0.78rem")};
  box-sizing: border-box;

  &:focus {
    outline: none;
  }

  &::placeholder {
    color: ${({ theme }) => theme.colors.subtleText};
  }

  &:disabled {
    opacity: 0.65;
    cursor: not-allowed;
  }
`;

const WarningPanel = styled(AuthSubtlePanel)`
  border-color: #f59e0b;
  background: ${({ theme }) =>
    theme.name === "dark" ? "rgba(245, 158, 11, 0.08)" : "rgba(245, 158, 11, 0.06)"};

  a {
    color: #f59e0b;
    text-decoration: underline;
    font-weight: 600;

    &:hover {
      color: #fbbf24;
    }
  }
`;

const WarningText = styled.div`
  color: ${({ theme }) => theme.colors.text};
  font-size: 0.78rem;
  line-height: 1.5;
`;

const SuccessIcon = styled.div`
  width: 2.4rem;
  height: 2.4rem;
  border-radius: 999px;
  margin: 0 auto 0.65rem;
  display: flex;
  align-items: center;
  justify-content: center;
  background: ${({ theme }) => theme.colors.buttonSuccessBg};
  color: ${({ theme }) => theme.colors.voteUp};
  font-size: 1.1rem;
  line-height: 1;
`;

const SuccessTitle = styled.div`
  color: ${({ theme }) => theme.colors.voteUp};
  font-size: 1rem;
  font-weight: 600;
  margin-bottom: 0.3rem;
`;

const SuccessText = styled.div`
  color: ${({ theme }) => theme.colors.text};
  font-size: 0.82rem;
  line-height: 1.5;
`;

const SuccessHandle = styled.div`
  margin-top: 0.35rem;
  color: ${({ theme }) => theme.colors.text};
  font-size: 0.86rem;
  font-weight: 600;
  font-family: "SFMono-Regular", Menlo, Monaco, Consolas, "Liberation Mono", monospace;
`;

const SuccessSubtext = styled.div`
  margin-top: 0.55rem;
  color: ${({ theme }) => theme.colors.subtleText};
  font-size: 0.7rem;
`;

const PrimaryButton = styled(Button)`
  border: ${({ theme }) => (theme.name === "dark" ? "0.5px" : "1px")} solid rgba(102, 126, 234, 0.45) !important;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%) !important;
  box-shadow: 0 6px 16px rgba(102, 126, 234, 0.22) !important;

  &:hover:not(:disabled) {
    border-color: rgba(118, 75, 162, 0.75) !important;
    box-shadow: 0 10px 22px rgba(102, 126, 234, 0.28) !important;
    filter: brightness(1.05);
  }
`;

function ChangeUsernameView({ state }) {
  const {
    currentUsername,
    usernameInput,
    setUsernameInput,
    submitting,
    buttonStatus,
    submitError,
    setSubmitError,
    cooldownUntil,
    userLevel,
    success,
    handleSubmit,
    canChangeName,
  } = useChangeUsername({ state });

  return (
    <ContentGrid>
      <Helmet>
        <title>Change Username | Mirage</title>
      </Helmet>
      {submitting && <BlockingOverlay />}
      <div>
        <ModernPostFeed>
          <HeaderRow>
            <HeaderTitle>Edit Username</HeaderTitle>
          </HeaderRow>
          <Divider />
          <PageWrapper>
            <PageTitle>Change your username</PageTitle>
            <PageDescription>
              {canChangeName
                ? "This is how people will find you on Mirage."
                : "Free tier accounts keep the Anon- prefix."}
            </PageDescription>

            <AuthStack>
              {!success && (
                <>
                  {!canChangeName && userLevel !== null && (
                    <WarningPanel>
                      <WarningText>
                        Free tier accounts will always have the &quot;Anon-&quot; prefix.{" "}
                        <Link to="/subscription">Upgrade to remove the &quot;Anon-&quot; prefix</Link>.
                      </WarningText>
                    </WarningPanel>
                  )}

                  <AuthPanel as="form" onSubmit={handleSubmit}>
                    <AuthLabel htmlFor="change-username-input" style={{ textAlign: "left" }}>New username</AuthLabel>
                    <InputRow $disabled={submitting}>
                      {!canChangeName && <InputPrefix>Anon-</InputPrefix>}
                      <InlineInput
                        id="change-username-input"
                        placeholder={
                          !canChangeName && currentUsername.startsWith("Anon-")
                            ? currentUsername.slice(5)
                            : currentUsername || "New username"
                        }
                        value={usernameInput}
                        $hasPrefix={!canChangeName}
                        onChange={(e) => {
                          const raw = e.target.value;
                          const cleaned = raw.replace(/[^A-Za-z0-9-]/g, "");
                          const maxLen = getMaxInputLength(!canChangeName);
                          setUsernameInput(cleaned.slice(0, maxLen ?? 100));
                          setSubmitError("");
                        }}
                        onKeyDown={async (e) => {
                          if (e.key === "Enter") {
                            e.preventDefault();
                            await handleSubmit(e);
                          }
                        }}
                        onPaste={(e) => {
                          e.preventDefault();
                        }}
                        maxLength={getMaxInputLength(!canChangeName) || 100}
                        disabled={submitting}
                        autoComplete="off"
                        autoCorrect="off"
                        autoCapitalize="off"
                        spellCheck="false"
                      />
                    </InputRow>
                    <AuthHelperText style={{ textAlign: "left" }}>Letters, numbers, and hyphens only.</AuthHelperText>

                    {submitError ? (
                      <AuthErrorMessage role="alert">{submitError}</AuthErrorMessage>
                    ) : null}

                    <AuthButtonRow>
                      <PrimaryButton
                        type="submit"
                        disabled={
                          submitting ||
                          Date.now() < cooldownUntil ||
                          usernameInput.trim() === ""
                        }
                        fullWidth
                        mobileFullWidth
                        size="sm"
                        loading={submitting}
                      >
                        {buttonStatus === "checking"
                          ? "Checking\u2026"
                          : buttonStatus === "preparing"
                            ? "Preparing\u2026"
                            : buttonStatus === "submitting"
                              ? "Submitting\u2026"
                              : buttonStatus === "verifying"
                                ? "Verifying\u2026"
                                : "Change Username"}
                      </PrimaryButton>
                    </AuthButtonRow>
                  </AuthPanel>
                </>
              )}

              {success && (
                <AuthPanel style={{ textAlign: "center" }}>
                  <SuccessIcon aria-hidden="true">✓</SuccessIcon>
                  <SuccessTitle>Username Changed!</SuccessTitle>
                  <SuccessText>Your new username is:</SuccessText>
                  <SuccessHandle>
                    {canChangeName ? usernameInput : "Anon-" + usernameInput}
                  </SuccessHandle>
                  <SuccessSubtext>Redirecting to profile…</SuccessSubtext>
                </AuthPanel>
              )}
            </AuthStack>
          </PageWrapper>
        </ModernPostFeed>
      </div>
    </ContentGrid>
  );
}

export default ChangeUsernameView;
