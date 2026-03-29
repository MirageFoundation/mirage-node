import { Helmet } from "react-helmet-async";
import styled from "styled-components";
import Button from "../components/Button.js";
import seedVault from "../../../utils/SeedVault";
import AuthPageShell from "../components/AuthPageShell.js";
import MobileHeader from "../components/MobileHeader.js";
import { ContentGrid, ModernPostFeed } from "../Layout";
import { useLogin } from "../../../logic/useLogin";
const Centered = styled.div`
    text-align: center;
    max-width: 800px;
    margin: 0 auto;
    padding: 0;
`;
const StyledTextArea = styled.textarea`    
    border: 1px solid ${({
  theme
}) => theme.colors.text};
    display: block;
    width: 100%;
    max-width: 400px;
    min-height: 120px;
    margin: 8px auto;    
    background-color: ${({
  theme
}) => theme.colors.panel};
    color: ${({
  theme
}) => theme.colors.subtleText};
    text-align: left;
    resize: vertical;
    font-size: 0.75rem;
    line-height: 1.5;
    padding: 0.75rem 1rem;
    box-sizing: border-box;
    font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;

    &:hover,&:focus {
        background-color: ${({
  theme
}) => theme.colors.panelAlt};
    }
`;
const ButtonWrapper = styled.div`
    display: flex;
    justify-content: center;
    margin: 12px auto;
    max-width: 400px;
`;
const IntroP = styled.p`
    margin: 0.35rem 0;
    line-height: 1.35;
    font-size: 0.75rem;
    color: ${({
  theme
}) => theme.colors.subtleText};
    max-width: 800px;
    margin-bottom: 0.7rem;
`;
const ErrorMessage = styled.div`
    color: #f66;
    margin-top: 0.5rem;
    font-size: 0.8rem;
    max-width: 400px;
    margin-left: auto;
    margin-right: auto;
`;
function LoginView({
  state,
  setCredentials
}) {
  const {
    navigate,
    seedPhrase,
    setSeedPhrase,
    error,
    setError,
    loading,
    handleSubmit
  } = useLogin({
    state,
    setCredentials
  });
  return <ContentGrid>
            <Helmet>
                <title>Sign In | Mirage</title>
            </Helmet>
            <div>
                <ModernPostFeed>
                    <MobileHeader />
                    <AuthPageShell activeTab="login">
                        <Centered>
                            <IntroP>
                                Sign in to your existing Mirage account with your 12-word recovery phrase<br />(each word is separated by a space):
                            </IntroP>

                            <form onSubmit={handleSubmit}>
                                <StyledTextArea placeholder="Enter your 12-word recovery phrase" value={seedPhrase} onChange={e => {
                setSeedPhrase(e.target.value.toLowerCase());
                setError('');
              }} autoCorrect="off" autoCapitalize="off" spellCheck="false" disabled={loading} />
                                <IntroP style={{
                marginTop: '0.5rem',
                fontSize: '0.7rem'
              }}>
                                    Your username will be automatically retrieved from the blockchain.
                                </IntroP>

                                {error && <ErrorMessage>{error}</ErrorMessage>}

                                <ButtonWrapper>
                                    <Button type="submit" disabled={loading} fullWidth loading={loading}>
                                        {loading ? 'Signing in...' : 'Sign In'}
                                    </Button>
                                </ButtonWrapper>
                            </form>

                            {seedVault.isLocked() && <div style={{
              marginTop: '1rem',
              fontSize: '0.6rem',
              color: '#999'
            }}>
                                    Encrypted vault detected.{' '}
                                    <span style={{
                color: '#4a9eff',
                cursor: 'pointer',
                fontSize: '0.6rem'
              }} onMouseEnter={e => e.target.style.textDecoration = 'underline'} onMouseLeave={e => e.target.style.textDecoration = 'none'} onClick={() => window.dispatchEvent(new CustomEvent('showVaultUnlock'))}>
                                        Sign in with that instead
                                    </span>?
                                </div>}

                            <div style={{
              marginTop: '0.25rem',
              fontSize: '0.6rem',
              color: '#999'
            }}>
                                Don't have an account?{' '}
                                <a href="/signup" style={{
                color: '#4a9eff',
                cursor: 'pointer',
                fontSize: '0.6rem',
                textDecoration: 'none'
              }} onMouseEnter={e => e.target.style.textDecoration = 'underline'} onMouseLeave={e => e.target.style.textDecoration = 'none'} onClick={e => {
                if (e.button === 0 && !e.metaKey && !e.ctrlKey && !e.shiftKey) {
                  e.preventDefault();
                  navigate('/signup');
                }
              }}>
                                    Create one here
                                </a>.
                            </div>
                        </Centered>
                    </AuthPageShell>
                </ModernPostFeed>
            </div>
        </ContentGrid>;
}
export default LoginView;