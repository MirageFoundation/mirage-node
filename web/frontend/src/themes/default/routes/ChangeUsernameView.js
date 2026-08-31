import { Helmet } from "react-helmet-async";
import styled from "styled-components";
import Button from "../components/Button.js";
import {
    AuthButtonRow,
    AuthErrorMessage,
    AuthHelperText,
    AuthLabel,
    AuthPanel,
    AuthStack,
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
  border: none !important;
  background: ${({ theme }) => theme.colors.followBtnBg} !important;
  color: #ffffff !important;
  box-shadow: none !important;
  transition: background 0.16s ease, box-shadow 0.16s ease !important;

  &:hover:not(:disabled) {
    background: ${({ theme }) => theme.colors.followBtnBgHover} !important;
    box-shadow: none !important;
  }
`;

function ChangeUsernameView({ state }) {
    const {
        usernameInput,
        setUsernameInput,
        submitting,
        buttonStatus,
        submitError,
        setSubmitError,
        cooldownUntil,
        success,
        handleSubmit,
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
                            This is how users will find you on Mirage.
                        </PageDescription>

                        <AuthStack>
                            {!success && (
                                <>
                                    <AuthPanel as="form" onSubmit={handleSubmit}>
                                        <AuthLabel htmlFor="change-username-input" style={{ textAlign: "left" }}>New username</AuthLabel>
                                        <InputRow $disabled={submitting}>
                                            <InlineInput
                                                id="change-username-input"
                                                placeholder="New username"
                                                value={usernameInput}
                                                onChange={(e) => {
                                                    const raw = e.target.value;
                                                    const cleaned = raw.replace(/[^A-Za-z0-9-]/g, "").replace(/^-+/, "");
                                                    const maxLen = getMaxInputLength();
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
                                                maxLength={getMaxInputLength() || 100}
                                                disabled={submitting}
                                                autoComplete="off"
                                                autoCorrect="off"
                                                autoCapitalize="off"
                                                spellCheck="false"
                                            />
                                        </InputRow>
                                        <AuthHelperText style={{ textAlign: "left" }}>Letters, numbers, and hyphens only. Must start with a letter or number.</AuthHelperText>

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
                                        {usernameInput}
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
