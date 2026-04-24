import { Helmet } from "react-helmet-async";
import styled from "styled-components";
import Button from "../components/Button.js";
import AuthPageShell, {
  AuthButtonRow,
  AuthHelperText,
  AuthStack,
} from "../components/AuthPageShell.js";
import { ContentGrid, ModernPostFeed } from "../Layout";
import { useWelcome } from "../../../logic/useWelcome";

const IdentityRow = styled.div`
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
  padding: 0.1rem 0;
`;

const IdentityLabel = styled.div`
  color: ${({ theme }) => theme.colors.subtleText};
  font-size: 0.65rem;
  font-weight: 500;
`;

const IdentityValue = styled.div`
  color: ${({ theme }) => theme.colors.text};
  font-size: 0.8rem;
  font-weight: 600;
  line-height: 1.25;
  word-break: break-word;
`;

const SectionLabel = styled.div`
  color: ${({ theme }) => theme.colors.text};
  font-size: 0.7rem;
  font-weight: 600;
`;

const SectionLabelRow = styled.div`
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 0.5rem;
  margin-bottom: 0.35rem;
`;

const SectionHint = styled.span`
  color: ${({ theme }) => theme.colors.subtleText};
  font-size: 0.65rem;
  font-weight: 500;
  font-variant-numeric: tabular-nums;
`;

const SeedGrid = styled.div`
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 0.35rem;
  padding: 0.55rem;
  border-radius: 0.55rem;
  border: 1px solid ${({ theme }) => theme.colors.border};
  background: ${({ theme }) => theme.colors.panelAlt};

  @media (max-width: 600px) {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
`;

const SeedWord = styled.div`
  min-width: 0;
  display: flex;
  align-items: baseline;
  gap: 0.4rem;
  padding: 0.4rem 0.5rem;
  border-radius: 0.4rem;
  background: ${({ theme }) => theme.colors.bg};
  color: ${({ theme }) => theme.colors.text};
  font-family: "SFMono-Regular", Menlo, Monaco, Consolas, "Liberation Mono", monospace;
  font-size: 0.72rem;
  line-height: 1.2;
  word-break: break-word;
`;

const SeedNumber = styled.span`
  color: ${({ theme }) => theme.colors.subtleText};
  font-size: 0.6rem;
  font-weight: 600;
  flex: 0 0 auto;
  min-width: 0.9rem;
`;

const WarningPanel = styled.div`
  display: flex;
  align-items: flex-start;
  gap: 0.55rem;
  padding: 0.6rem 0.75rem;
  border-radius: 0.55rem;
  border: 0.5px solid #f59e0b;
  background: ${({ theme }) =>
    theme.name === "dark" ? "rgba(245, 158, 11, 0.08)" : "rgba(245, 158, 11, 0.06)"};
  color: ${({ theme }) => theme.colors.text};
  font-size: 0.7rem;
  line-height: 1.5;
`;

const WarningIcon = styled.span`
  flex: 0 0 auto;
  color: #f59e0b;
  font-size: 0.85rem;
  line-height: 1.2;
`;

const WarningBody = styled.div`
  min-width: 0;

  b {
    font-weight: 600;
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

const SecondaryButton = styled(Button)`
  border: 1px solid ${({ theme }) => theme.colors.border} !important;
  background: ${({ theme }) => theme.colors.panelAlt} !important;
  color: ${({ theme }) => theme.colors.text} !important;
  box-shadow: none !important;
  transition: border-color 0.15s ease !important;

  &:hover:not(:disabled) {
    border-color: ${({ theme }) => theme.colors.borderStrong} !important;
    background: ${({ theme }) => theme.colors.panelAlt} !important;
  }
`;

const ActionRow = styled.div`
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0.45rem;

  @media (max-width: 600px) {
    grid-template-columns: 1fr;
  }
`;

function WelcomeView({ state }) {
  const {
    navigate,
    copied,
    setCopied,
    username,
    seedPhrase,
  } = useWelcome({ state });

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

  const words = seedPhrase.split(" ").filter(Boolean);

  return (
    <ContentGrid>
      <Helmet>
        <title>Welcome | Mirage</title>
      </Helmet>
      <div>
        <ModernPostFeed>
          <AuthPageShell
            title="Your account is ready"
            description="Save your 12-word recovery phrase below — it's the only way to restore this account."
          >
            <AuthStack>
              <IdentityRow>
                <IdentityLabel>Signed in as</IdentityLabel>
                <IdentityValue>{username}</IdentityValue>
              </IdentityRow>

              <div>
                <SectionLabelRow>
                  <SectionLabel>Recovery phrase</SectionLabel>
                  <SectionHint>{words.length}/12 words</SectionHint>
                </SectionLabelRow>
                <SeedGrid>
                  {words.map((word, index) => (
                    <SeedWord key={index}>
                      <SeedNumber>{index + 1}</SeedNumber>
                      <span>{word}</span>
                    </SeedWord>
                  ))}
                </SeedGrid>
                <AuthHelperText style={{ marginTop: "0.35rem" }}>
                  These 12 words are the only way to restore your account on another device.
                </AuthHelperText>
              </div>

              <WarningPanel role="note">
                <WarningIcon aria-hidden="true">⚠</WarningIcon>
                <WarningBody>
                  Store this phrase <b>offline</b>. Anyone with these words can access your account.
                </WarningBody>
              </WarningPanel>

              <AuthButtonRow>
                <ActionRow>
                  <PrimaryButton onClick={copyToClipboard} size="sm" fullWidth mobileFullWidth>
                    {copied ? "Copied" : "Copy phrase"}
                  </PrimaryButton>
                  <SecondaryButton onClick={() => navigate("/")} size="sm" fullWidth mobileFullWidth>
                    Continue
                  </SecondaryButton>
                </ActionRow>
              </AuthButtonRow>
            </AuthStack>
          </AuthPageShell>
        </ModernPostFeed>
      </div>
    </ContentGrid>
  );
}

export default WelcomeView;
