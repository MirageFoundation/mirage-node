import { Helmet } from "react-helmet-async";
import styled from "styled-components";
import Button from "../components/Button.js";
import { Link } from "react-router-dom";
import MobileHeader from "../components/MobileHeader.js";
import { ContentGrid, ModernPostFeed, TabbedContainer, ContainerTab, ContainerBody } from "../Layout";
import { getMaxInputLength } from "../../../config/chainParams";
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
const Centered = styled.div`
    max-width: 500px;
    margin: 0 auto;
    text-align: center;
    padding: 0;
    box-sizing: border-box;
`;
const InputWrapper = styled.div`
    display: flex;
    align-items: center;
    border: 1px solid ${({
  theme
}) => theme.colors.border};
    background-color: ${({
  theme
}) => theme.colors.panelAlt};
    border-radius: ${({
  theme
}) => theme.layout.inputRadius};
    margin: 0.75rem auto;
    overflow: hidden;
    opacity: ${({
  $disabled
}) => $disabled ? 0.5 : 1};
    pointer-events: ${({
  $disabled
}) => $disabled ? 'none' : 'auto'};
    max-width: 100%;
    box-sizing: border-box;

    &:hover, &:focus-within {
        border-color: ${({
  $disabled,
  theme
}) => $disabled ? theme.colors.border : theme.colors.link};
    }
`;
const InputPrefix = styled.span`
    padding: 0.41rem 0 0.5rem 0.75rem;
    color: ${({
  theme
}) => theme.colors.text};
    font-size: 0.85rem;
    line-height: 1.3;
    user-select: none;
    white-space: nowrap;
`;
const StyledInputBox = styled.input`    
    border: none;
    flex: 1;
    min-width: 0;
    width: 100%;
    background-color: transparent;
    color: ${({
  theme
}) => theme.colors.text};
    text-align: ${({
  $hasPrefix
}) => $hasPrefix ? 'left' : 'center'};
    resize: none;
    border-radius: ${({
  theme
}) => theme.layout.inputRadius};
    font-size: ${({
  theme
}) => theme.layout.inputSize};
    line-height: 1.3;
    padding: ${({
  theme
}) => theme.layout.inputPadding};
    padding-left: ${({
  $hasPrefix
}) => $hasPrefix ? '0.15rem' : '0.75rem'};
    box-sizing: border-box;
    text-overflow: ellipsis;

    &:focus {
        outline: none;
        box-shadow: ${({
  theme
}) => theme.layout.focusRing};
    }

    &::placeholder {
        color: ${({
  theme
}) => theme.colors.subtleText};
    }

    &:disabled {
        opacity: 0.5;
        cursor: not-allowed;
    }
`;
const ButtonWrapper = styled.div`
    margin-top: 0.5rem;
`;
const WarningBox = styled.div`
    background-color: rgba(245, 158, 11, 0.1);
    border: 1px solid #f59e0b;
    padding: ${({
  theme
}) => theme.layout.bannerPadding};
    border-radius: ${({
  theme
}) => theme.layout.bannerRadius};
    margin-bottom: 0.75rem;
    font-size: ${({
  theme
}) => theme.layout.bannerSize};
    color: ${({
  theme
}) => theme.colors.text};
    text-align: left;
    box-sizing: border-box;
    word-wrap: break-word;
    
    a {
        color: #f59e0b;
        text-decoration: underline;
        font-weight: 600;
        
        &:hover {
            color: #fbbf24;
        }
    }
`;
const SuccessBox = styled.div`
    text-align: center;
    border-radius: ${({
  theme
}) => theme.layout.containerRadius};
    padding: ${({
  theme
}) => theme.layout.containerPadding};
`;
const SuccessTitle = styled.div`
    font-size: 1.5rem;
    font-weight: bold;
    color: #4ade80;
    margin-bottom: 0.75rem;
`;
const SuccessText = styled.div`
    font-size: 1rem;
    color: ${({
  theme
}) => theme.colors.text};
    margin-bottom: 0.5rem;
`;
const SuccessSubtext = styled.div`
    font-size: 0.8rem;
    color: ${({
  theme
}) => theme.colors.subtleText};
`;
function ChangeUsernameView({
  state
}) {
  const {
    location,
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
    canChangeName
  } = useChangeUsername({
    state
  });
  return <>
            <Helmet>
                <title>Change Username | Mirage</title>
            </Helmet>
            {submitting && <BlockingOverlay />}
            <ContentGrid>
                <div>
                    <ModernPostFeed>
                        <MobileHeader />
                        <TabbedContainer>
                            <ContainerTab>Change Username</ContainerTab>
                            <ContainerBody>
                                <Centered>
                                    {!success && <>
                                            {!canChangeName && userLevel !== null && <WarningBox>
                                                    Free tier accounts will always have the "Anon-" prefix. <Link to="/subscription">Upgrade to remove the "Anon-" prefix</Link>.
                                                </WarningBox>}


                                            <InputWrapper $disabled={submitting}>
                                                {!canChangeName && <InputPrefix>Anon-</InputPrefix>}
                                                <StyledInputBox placeholder={!canChangeName && currentUsername.startsWith('Anon-') ? currentUsername.slice(5) : currentUsername || 'New username'} value={usernameInput} $hasPrefix={!canChangeName} onChange={e => {
                      const raw = e.target.value;
                      const cleaned = raw.replace(/[^A-Za-z0-9-]/g, "");
                      const maxLen = getMaxInputLength(!canChangeName);
                      // If params not loaded yet, allow up to 100 chars temporarily
                      setUsernameInput(cleaned.slice(0, maxLen ?? 100));
                      setSubmitError("");
                    }} onKeyDown={async e => {
                      if (e.key === 'Enter') {
                        e.preventDefault();
                        await handleSubmit(e);
                      }
                    }} onPaste={e => {
                      // Block paste to prevent accidental seed phrase entry
                      e.preventDefault();
                    }} maxLength={getMaxInputLength(!canChangeName) || 100} disabled={submitting} />
                                            </InputWrapper>

                                            <ButtonWrapper>
                                                <Button onClick={handleSubmit} disabled={submitting || Date.now() < cooldownUntil || usernameInput.trim() === ''} fullWidth loading={submitting}>
                                                    {buttonStatus === "checking" ? 'Checking...' : buttonStatus === "preparing" ? 'Preparing...' : buttonStatus === "submitting" ? 'Submitting...' : buttonStatus === "verifying" ? 'Verifying...' : 'Change Username'}
                                                </Button>
                                            </ButtonWrapper>

                                            {submitError && <div style={{
                    color: '#f66',
                    marginTop: '0.75rem',
                    fontSize: '0.8rem'
                  }}>{submitError}</div>}
                                        </>}

                                    {success && <SuccessBox>
                                            <SuccessTitle>Username Changed!</SuccessTitle>
                                            <SuccessText>Your new username is:</SuccessText>
                                            <SuccessText><strong>{canChangeName ? usernameInput : 'Anon-' + usernameInput}</strong></SuccessText>
                                            <SuccessSubtext>Redirecting to profile...</SuccessSubtext>
                                        </SuccessBox>}
                                </Centered>
                            </ContainerBody>
                        </TabbedContainer>
                    </ModernPostFeed>
                </div>
            </ContentGrid>
        </>;
}
export default ChangeUsernameView;