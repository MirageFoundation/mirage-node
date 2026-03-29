import { Helmet } from "react-helmet-async";
import styled from "styled-components";
import Button from "../components/Button.js";
import MobileHeader from "../components/MobileHeader.js";
import { ContentGrid, ModernPostFeed, ContainerBody } from "../Layout";
import { useWelcome } from "../../../logic/useWelcome";
const Centered = styled.div`
    text-align: center;
    max-width: 100%;
    margin: 0 auto;
    padding: 0.5rem 0;
    overflow: visible;
    
    
    @media (max-width: 1000px) {
        padding: 0.25rem 0;
    }
`;
const SeedGrid = styled.div`
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 0.4rem;
    max-width: 100%;
    margin: 0.75rem auto;
    padding: 0.75rem;
    background-color: ${({
  theme
}) => theme.colors.panel};
    border: 1px solid ${({
  theme
}) => theme.colors.border};
    border-radius: 4px;
    position: relative;
    box-sizing: border-box;
    
    @media (max-width: 1000px) {
        grid-template-columns: repeat(3, 1fr);
        padding: 0.5rem;
        gap: 0.3rem;
    }
`;
const SeedWord = styled.div`
    background-color: ${({
  theme
}) => theme.colors.panelAlt};
    border: 1px solid ${({
  theme
}) => theme.colors.border};
    border-radius: 3px;
    padding: 0.3rem 0.2rem;
    text-align: left;
    font-size: 0.75rem;
    color: ${({
  theme
}) => theme.colors.text};
    font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
    display: flex;
    align-items: center;
    gap: 0.2rem;
    white-space: nowrap;
    word-break: normal;
    overflow-wrap: normal;
    
    &:before {
        content: attr(data-index);
        color: ${({
  theme
}) => theme.colors.subtleText};
        font-size: 0.5rem;
        min-width: 12px;
        font-weight: bold;
    }
    
    @media (max-width: 400px) {
        font-size: 0.7rem;
        padding: 0.25rem 0.15rem;
        gap: 0.1rem;
        
        &:before {
            font-size: 0.45rem;
            min-width: 10px;
        }
    }
`;
const InfoSection = styled.div`
    margin: 0.5rem 0 0 0;
`;
const WarningBox = styled.div`
    border: 1px solid ${({
  theme
}) => theme.colors.border};
    color: ${({
  theme
}) => theme.colors.text};
    padding: 0.5rem;
    border-radius: 4px;
    margin: 0.5rem 0;
    font-size: 0.75rem;
    line-height: 1.3;
    
    .warning-title {
        font-weight: bold;
        margin-bottom: 0.3rem;
        font-size: 0.85rem;
        
        &:before {
            content: "⚠️ ";
            margin-right: 0.2rem;
        }
    }
`;
const WelcomeHeading = styled.div`
    text-align: center;
    font-size: 2.0rem;
    color: ${({
  theme
}) => theme.name === 'light' ? theme.colors.text : theme.colors.subtleText};
    margin-bottom: 0.75rem;
    margin-top: 0.5rem;
    
    @media (max-width: 1000px) {
        font-size: 1.25rem;
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 0.25rem;
    }
`;
const WelcomeUsername = styled.strong`
    font-size: 2.0rem;
    word-break: break-all;
    
    @media (max-width: 1000px) {
        font-size: 1.25rem;
        display: block;
    }
`;
const DesktopOnly = styled.span`
    @media (max-width: 1000px) {
        display: none;
    }    
`;
const ButtonRow = styled.div`
    display: flex;
    justify-content: center;
    gap: 0.75rem;
    margin-top: 1rem;
    
    @media (max-width: 1000px) {
        flex-direction: column;
        align-items: center;
        gap: 0.5rem;
        margin-top: 0.5rem;
    }
`;
function WelcomeView({
  state
}) {
  const {
    navigate,
    location,
    copied,
    setCopied,
    username,
    seedPhrase
  } = useWelcome({
    state
  });
  if (!username || !seedPhrase) {
    return null;
  }
  const copyToClipboard = async () => {
    try {
      await navigator.clipboard.writeText(seedPhrase);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (_) {}
  };
  return <ContentGrid>
            <Helmet>
                <title>Welcome | Mirage</title>
            </Helmet>
            <div>
                <ModernPostFeed>
                    <MobileHeader />
                    <ContainerBody style={{
          overflow: 'visible'
        }}>
                        <Centered>
                            <WelcomeHeading>
                                <span>Welcome<DesktopOnly>, </DesktopOnly></span>
                                <WelcomeUsername>{username}<DesktopOnly>!</DesktopOnly></WelcomeUsername>
                            </WelcomeHeading>

                            <InfoSection>
                                <WarningBox>
                                    <div className="warning-title">Important: Below Is Your Recovery Phrase</div>
                                    This 12-word phrase is the ONLY way to recover your account. Write it down and store it safely offline. Anyone with this phrase can access your account!
                                </WarningBox>

                                <SeedGrid>
                                    {seedPhrase.split(' ').map((word, index) => <SeedWord key={index} data-index={index + 1}>
                                            {word}
                                        </SeedWord>)}
                                </SeedGrid>
                            </InfoSection>

                            <ButtonRow>
                                <Button onClick={copyToClipboard} copied={copied} minWidth="10rem" mobileFullWidth>
                                    {copied ? 'Copied!' : 'Copy Recovery Phrase'}
                                </Button>
                                <Button onClick={() => navigate('/')} mobileFullWidth>
                                    Continue to Mirage
                                </Button>
                            </ButtonRow>
                        </Centered>
                    </ContainerBody>
                </ModernPostFeed>
            </div>
        </ContentGrid>;
}
export default WelcomeView;