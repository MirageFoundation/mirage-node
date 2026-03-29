import { Helmet } from "react-helmet-async";
import styled from "styled-components";
import Button from "../components/Button.js";
import AuthPageShell from "../components/AuthPageShell.js";
import Sidebar from "../components/Sidebar.js";
import TopBar from "../components/TopBar.js";
import MobileHeader from "../components/MobileHeader.js";
import { ContentGrid, ModernPostFeed } from "../../../styled/Layout";
import { getMaxInputLength } from "../../../config/chainParams";
import { formatError } from "../../../utils/errorMessages";
import { useCreateAccount } from "../../../logic/useCreateAccount";
const Centered = styled.div`
    text-align: center;
    max-width: 800px;
    margin: 0 auto;
    padding: 0 0.5rem;
`;
const StyledInfo = styled.div`
    margin-top: 0.5rem;
    margin-left: 0;
    margin-right: 0;
    padding: 1.5rem 1.25rem;
    background-color: ${({
  theme
}) => theme.colors.panelAlt};
    border: 1px solid ${({
  theme
}) => theme.colors.border};
    border-radius: 8px;
    text-align: center;
    
    @media (max-width: 1000px) {
        padding: 1rem 0.75rem;
    }
`;
const StyledInputBox = styled.input`    
    border: 1px solid ${({
  theme
}) => theme.colors.text};
    display: block;
    width: 100%;
    max-width: 320px;
    margin: 8px auto;    
    background-color: ${({
  theme
}) => theme.colors.panel};
    color: ${({
  theme
}) => theme.colors.subtleText};
    text-align: center;
    resize: none;
    font-size: 0.7rem;
    line-height: 1.0;
    padding: 0.15rem 0.35rem;
    box-sizing: border-box;

    &:hover,&:focus {
        background-color: ${({
  theme
}) => theme.colors.panelAlt};
    }
`;
const ButtonWrapper = styled.div`
    display: flex;
    justify-content: center;
    margin: 6px auto;
    max-width: 320px;
`;
const IntroP = styled.p`
    margin: 0 0 1rem 0;
    line-height: 1.6;
    font-size: 0.85rem;
    color: ${({
  theme
}) => theme.colors.text};
    max-width: 800px;
    text-align: justify;
    text-align-last: center;
    
    &:last-of-type {
        margin-bottom: 0;
    }
    
    @media (max-width: 1000px) {
        /* Root font is 130% on mobile, so use smaller rem to compensate */
        font-size: 0.6rem;
        line-height: 1.5;
    }
`;
const WelcomeTitle = styled.div`
    font-size: 1.5rem;
    font-weight: 600;
    margin-bottom: 1.25rem;
    color: ${({
  theme
}) => theme.colors.text};
    text-align: center;
    @media (max-width: 1000px) {
        font-size: 1.25rem;
        margin-bottom: 1rem;
    }
`;
const UsernameLabel = styled.div`
    font-size: 1.0rem;
    font-weight: 600;
    margin-top: 1.75rem;
    margin-bottom: 0.75rem;
    color: ${({
  theme
}) => theme.colors.text};
`;
function CreateAccountView({
  state,
  setCredentials
}) {
  const {
    location,
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
    configFetchDone
  } = useCreateAccount({
    state,
    setCredentials
  });
  if (!nodeConfig) {
    return <ContentGrid>
                <Helmet>
                    <title>Create Account | Mirage</title>
                </Helmet>
                <Sidebar currentPath={location.pathname} state={state} />
                <div>
                    <TopBar state={state} />
                    <ModernPostFeed>
                        <MobileHeader />
                        <AuthPageShell activeTab="create">
                            <Centered>
                                <StyledInfo>
                                    {configFetchDone ? <>
                                            <WelcomeTitle>Unavailable</WelcomeTitle>
                                            <IntroP>
                                                Unable to load node configuration. Please refresh the page.
                                            </IntroP>
                                        </> : <WelcomeTitle>Loading...</WelcomeTitle>}
                                </StyledInfo>
                            </Centered>
                        </AuthPageShell>
                    </ModernPostFeed>
                </div>
            </ContentGrid>;
  }

  // If registration is disabled on this node, show unavailable message
  if (!registrationEnabled) {
    return <ContentGrid>
                <Helmet>
                    <title>Create Account | Mirage</title>
                </Helmet>
                <Sidebar currentPath={location.pathname} state={state} />
                <div>
                    <TopBar state={state} />
                    <ModernPostFeed>
                        <MobileHeader />
                        <AuthPageShell activeTab="create">
                            <Centered>
                                <StyledInfo>
                                    <WelcomeTitle>Account Creation Unavailable</WelcomeTitle>
                                    <IntroP>
                                        Account creation is not available on this node.
                                    </IntroP>
                                </StyledInfo>
                            </Centered>
                        </AuthPageShell>
                    </ModernPostFeed>
                </div>
            </ContentGrid>;
  }
  return <ContentGrid>
            <Helmet>
                <title>Create Account | Mirage</title>
            </Helmet>
            <Sidebar currentPath={location.pathname} state={state} />
            <div>
                <TopBar state={state} />
                <ModernPostFeed>
                    <MobileHeader />
                    <AuthPageShell activeTab="create">
                        <Centered>
                            <StyledInfo>
                                <WelcomeTitle>{fromRecovery ? 'Create Your Account' : 'Welcome to Mirage!'}</WelcomeTitle>
                                <div>
                                    {fromRecovery ? <>
                                            <IntroP style={{
                    color: '#f66'
                  }}>
                                                No account was found on the blockchain for this recovery phrase, but you can create a new account using it now.
                                            </IntroP>
                                            <IntroP>
                                                Free accounts are prefixed with "Anon-" and run a small proof-of-work on your device to prevent spam.
                                                Choose a username below to continue.
                                            </IntroP>
                                        </> : <>
                                            <IntroP>
                                                Mirage is a fully decentralized social network built on its own blockchain, designed to be 100% censorship resistant.
                                            </IntroP>
                                            <IntroP>
                                                Free accounts are prefixed with "Anon-" and run a small proof-of-work on your device to prevent spam.
                                                You can upgrade anytime with MIRAGE tokens to remove the prefix, unlock cosmetic perks, and access premium features.
                                            </IntroP>
                                        </>}
                                </div>
                                {inviteCodeRequired && (referrerStatus === "valid" ? <>
                                            <UsernameLabel>Invite code:</UsernameLabel>
                                            <StyledInputBox value="Code applied" readOnly disabled style={{
                  opacity: 0.7,
                  cursor: 'default',
                  color: '#7ecf7e',
                  pointerEvents: 'none'
                }} tabIndex={-1} />
                                            {referrerAvailable > 0 && <div style={{
                  color: '#f5a623',
                  fontSize: '0.7rem',
                  marginTop: '0.25rem'
                }}>
                                                    Only {referrerAvailable} {referrerAvailable === 1 ? 'code' : 'codes'} left
                                                </div>}
                                        </> : referrerStatus === "checking" ? <>
                                            <UsernameLabel>Invite code:</UsernameLabel>
                                            <StyledInputBox value="Checking referral..." readOnly disabled style={{
                  opacity: 0.5,
                  cursor: 'default',
                  pointerEvents: 'none'
                }} tabIndex={-1} />
                                        </> : referrerStatus === "invalid" && refFromUrl ? <div style={{
                marginTop: '1.5rem',
                padding: '1rem 1.25rem',
                borderRadius: '8px',
                border: '1px solid var(--border-color, #444)',
                background: 'var(--panel-alt, #2A2E33)',
                textAlign: 'center'
              }}>
                                            <div style={{
                  color: '#f66',
                  fontSize: '0.85rem',
                  fontWeight: 600
                }}>
                                                {formatError(referrerError)}
                                            </div>
                                            <div style={{
                  marginTop: '0.75rem',
                  fontSize: '0.8rem',
                  opacity: 0.7
                }}>
                                                Have an invite code? <a href="/signup" style={{
                    color: 'inherit',
                    textDecoration: 'underline'
                  }}>Enter it manually</a>
                                            </div>
                                        </div> : <>
                                            <UsernameLabel>Enter your invite code:</UsernameLabel>
                                            <StyledInputBox placeholder="XXXX-XXXX" value={inviteCode} onChange={e => {
                  const raw = e.target.value.toUpperCase();
                  const alphanumOnly = raw.replace(/[^A-Z0-9]/g, "");
                  const limited = alphanumOnly.slice(0, 8);
                  const formatted = limited.length > 4 ? limited.slice(0, 4) + '-' + limited.slice(4) : limited;
                  setInviteCode(formatted);
                  setSubmitError("");
                }} maxLength={9} name="invite-code-entry" id="invite-code-entry" autoComplete="one-time-code" autoCorrect="off" autoCapitalize="characters" spellCheck="false" data-lpignore="true" data-1p-ignore="true" data-bwignore="true" data-form-type="other" />
                                        </>)}
                                {!(referrerStatus === "invalid" && refFromUrl) && <>
                                        <UsernameLabel>Choose your username:</UsernameLabel>
                                        <StyledInputBox placeholder="" value={usernameInput} onChange={e => {
                  const raw = e.target.value;
                  const cleaned = raw.replace(/[^A-Za-z0-9-]/g, "");
                  const maxLen = getMaxInputLength(true);
                  setUsernameInput(cleaned.slice(0, maxLen ?? 100));
                  setSubmitError("");
                }} onKeyDown={async e => {
                  if (e.key === 'Enter') {
                    e.preventDefault();
                    await handleContinue(e);
                  }
                }} onPaste={e => {
                  e.preventDefault();
                }} maxLength={getMaxInputLength(true) || 100} name="display-name-entry" id="display-name-entry" autoComplete="one-time-code" autoCorrect="off" autoCapitalize="off" spellCheck="false" data-lpignore="true" data-1p-ignore="true" data-bwignore="true" data-form-type="other" />
                                        <ButtonWrapper>
                                            <Button onClick={handleContinue} disabled={submitting || Date.now() < cooldownUntil || usernameFinal.trim() === '' || referrerStatus === "checking"} fullWidth size="sm" loading={submitting}>
                                                {buttonStatus === "preparing" ? 'Preparing...' : buttonStatus === "submitting" ? 'Submitting...' : buttonStatus === "verifying" ? 'Verifying...' : 'Continue'}
                                            </Button>
                                        </ButtonWrapper>
                                        {submitError && <div style={{
                  color: '#f66',
                  marginTop: '0.5rem',
                  fontSize: '0.8rem'
                }}>{submitError}</div>}
                                    </>}
                            </StyledInfo>
                        </Centered>
                    </AuthPageShell>
                </ModernPostFeed>
            </div>
        </ContentGrid>;
}
export default CreateAccountView;