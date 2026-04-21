import { Helmet } from "react-helmet-async";
import styled from "styled-components";
import Button from "../components/Button.js";
import AuthPageShell, {
  AuthPanel,
  AuthStack,
  AuthSubtlePanel,
} from "../components/AuthPageShell.js";
import { ContentGrid, ModernPostFeed } from "../Layout";
import { useWelcome } from "../../../logic/useWelcome";

const IdentityRow = styled.div`
  display: flex;
  align-items: center;
  gap: 0.7rem;
`;

const IdentityAvatar = styled.div`
  width: 2.4rem;
  height: 2.4rem;
  flex: 0 0 auto;
  border-radius: 0.85rem;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #ffffff;
  font-size: 0.95rem;
  font-weight: 600;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  box-shadow: 0 8px 18px rgba(102, 126, 234, 0.28);
`;

const IdentityBody = styled.div`
  min-width: 0;
  flex: 1;
`;

const IdentityLabel = styled.div`
  color: ${({ theme }) => theme.colors.subtleText};
  font-size: 0.62rem;
  font-weight: 600;
  letter-spacing: 0.05em;
  text-transform: uppercase;
`;

const IdentityValue = styled.div`
  margin-top: 0.18rem;
  color: ${({ theme }) => theme.colors.text};
  font-size: 0.95rem;
  font-weight: 600;
  line-height: 1.2;
  word-break: break-word;
`;

const SuccessPill = styled.span`
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  padding: 0.22rem 0.5rem;
  border-radius: 999px;
  background: ${({ theme }) => theme.colors.buttonSuccessBg};
  color: ${({ theme }) => theme.colors.voteUp};
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

const SectionLabelRow = styled.div`
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
  margin-top: 0.85rem;
`;

const SectionTitle = styled.div`
  color: ${({ theme }) => theme.colors.text};
  font-size: 0.7rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
`;

const PhraseHelper = styled.p`
  margin: 0.35rem 0 0;
  color: ${({ theme }) => theme.colors.subtleText};
  font-size: 0.7rem;
  line-height: 1.45;
`;

const PhraseContainer = styled.div`
  margin-top: 0.55rem;
  padding: 0.55rem;
  border-radius: 0.85rem;
  border: 1px solid ${({ theme }) => theme.colors.border};
  background: ${({ theme }) => theme.name === "light" ? "rgb(243, 243, 243)" : "rgb(36, 39, 45)"};
`;

const SeedGrid = styled.div`
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 0.42rem;

  @media (max-width: 600px) {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
`;

const SeedWord = styled.div`
  min-width: 0;
  display: flex;
  align-items: baseline;
  gap: 0.4rem;
  padding: 0.5rem 0.6rem;
  border-radius: 0.7rem;
  border: 1px solid ${({ theme }) => theme.colors.border};
  background: ${({ theme }) => theme.name === "light" ? "#FFFFFF" : "rgb(25, 28, 31)"};
  color: ${({ theme }) => theme.colors.text};
  font-family: "SFMono-Regular", Menlo, Monaco, Consolas, "Liberation Mono", monospace;
  font-size: 0.74rem;
  line-height: 1.2;
  word-break: break-word;
`;

const SeedNumber = styled.span`
  color: ${({ theme }) => theme.colors.subtleText};
  font-size: 0.6rem;
  font-weight: 600;
  flex: 0 0 auto;
`;

const WarningBox = styled.div`
  display: flex;
  align-items: flex-start;
  gap: 0.55rem;
  margin-top: 0.7rem;
  padding: 0.6rem 0.7rem;
  border-radius: 0.75rem;
  border: 1px solid rgba(245, 158, 11, 0.35);
  background: rgba(245, 158, 11, 0.12);
`;

const WarningIcon = styled.div`
  width: 1.5rem;
  height: 1.5rem;
  flex: 0 0 auto;
  border-radius: 0.5rem;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(245, 158, 11, 0.25);
  color: #f59e0b;
  font-size: 0.85rem;
`;

const WarningText = styled.div`
  color: ${({ theme }) => theme.colors.text};
  font-size: 0.7rem;
  line-height: 1.45;
`;

const ButtonStack = styled.div`
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0.45rem;
  margin-top: 0.85rem;

  @media (max-width: 600px) {
    grid-template-columns: 1fr;
  }
`;

const PrimaryButton = styled(Button)`
  border: none !important;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%) !important;
  box-shadow: ${({ theme }) => theme.name === "light"
        ? "0 4px 12px rgba(102, 126, 234, 0.18)"
        : "0 2px 8px rgba(0, 0, 0, 0.35)"} !important;
  transition: filter 0.16s ease, box-shadow 0.16s ease !important;

  &:hover:not(:disabled) {
    filter: brightness(1.08);
    box-shadow: ${({ theme }) => theme.name === "light"
        ? "0 6px 16px rgba(102, 126, 234, 0.22)"
        : "0 3px 10px rgba(0, 0, 0, 0.4)"} !important;
  }
`;

const SecondaryButton = styled(Button)`
  border: 1px solid ${({ theme }) => theme.colors.border} !important;
  background: ${({ theme }) => theme.name === "light" ? "rgb(243, 243, 243)" : "rgb(36, 39, 45)"} !important;
  color: ${({ theme }) => theme.colors.text} !important;
  box-shadow: none !important;
  transition: background 0.16s ease !important;

  &:hover:not(:disabled) {
    background: ${({ theme }) => theme.name === "light" ? "rgb(230, 235, 238)" : "rgb(53, 61, 65)"} !important;
    box-shadow: none !important;
  }
`;

function WelcomeView({
  state,
}) {
  const {
    navigate,
    copied,
    setCopied,
    username,
    seedPhrase,
  } = useWelcome({
    state,
  });

  if (!username || !seedPhrase) {
    return null;
  }

  const initial = (username || "?").trim().replace(/^Anon-/i, "").slice(0, 1).toUpperCase() || "M";

  const copyToClipboard = async () => {
    try {
      await navigator.clipboard.writeText(seedPhrase);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (_) {}
  };

  return (
    <ContentGrid>
      <Helmet>
        <title>Welcome | Mirage</title>
      </Helmet>
      <div>
        <ModernPostFeed>
          <AuthPageShell
            showTabs={false}
            eyebrow="Account ready"
            title="Welcome to Mirage"
            description="Save your recovery phrase below — it's the only way to restore this account."

          >
            <AuthStack>
              <AuthSubtlePanel>
                <IdentityRow>
                  <IdentityAvatar aria-hidden="true">{initial}</IdentityAvatar>
                  <IdentityBody>
                    <IdentityLabel>Signed in as</IdentityLabel>
                    <IdentityValue>{username}</IdentityValue>
                  </IdentityBody>
                  <SuccessPill>Live</SuccessPill>
                </IdentityRow>
              </AuthSubtlePanel>

              <AuthPanel>
                <SectionLabelRow>
                  <SectionTitle>Recovery phrase</SectionTitle>
                  <SuccessPill>12 words</SuccessPill>
                </SectionLabelRow>
                <PhraseHelper>
                  These 12 words are the only way to restore your account on another device.
                </PhraseHelper>

                <PhraseContainer>
                  <SeedGrid>
                    {seedPhrase.split(" ").map((word, index) => (
                      <SeedWord key={index}>
                        <SeedNumber>{index + 1}</SeedNumber>
                        <span>{word}</span>
                      </SeedWord>
                    ))}
                  </SeedGrid>
                </PhraseContainer>

                <WarningBox>
                  <WarningIcon aria-hidden="true">⚠</WarningIcon>
                  <WarningText>
                    Store this phrase offline. Anyone with these words can access your account.
                  </WarningText>
                </WarningBox>

                <ButtonStack>
                  <PrimaryButton onClick={copyToClipboard} copied={copied} size="sm" fullWidth mobileFullWidth>
                    {copied ? "Copied!" : "Copy phrase"}
                  </PrimaryButton>
                  <SecondaryButton onClick={() => navigate("/")} size="sm" fullWidth mobileFullWidth>
                    Continue
                  </SecondaryButton>
                </ButtonStack>
              </AuthPanel>
            </AuthStack>
          </AuthPageShell>
        </ModernPostFeed>
      </div>
    </ContentGrid>
  );
}

export default WelcomeView;
