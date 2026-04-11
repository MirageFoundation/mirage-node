import React from "react";
import styled, { css } from "styled-components";
import { useNavigate } from "react-router-dom";

const getOnboardingContainerBg = (theme) =>
    theme.name === "light" ? "#FFFFFF" : "rgb(25, 28, 31)";

const getInputBg = (theme) =>
    theme.name === "light" ? "rgb(230, 235, 238)" : "rgb(44, 50, 54)";

const getInputHoverBg = (theme) =>
    theme.name === "light" ? "rgb(221, 228, 232)" : "rgb(53, 61, 65)";

const getTileBg = (theme) =>
    theme.name === "light" ? "rgb(243, 243, 243)" : "rgb(36, 39, 45)";

const Shell = styled.section`
    width: 100%;
    display: flex;
    justify-content: center;
    padding: 0.6rem 0 1.2rem;
    box-sizing: border-box;

    @media (max-width: 1000px) {
        padding: 0;
    }
`;

const Card = styled.div`
    width: min(60%, 30rem);
    background: ${({ theme }) => getOnboardingContainerBg(theme)};
    border: 1px solid ${({ theme }) => theme.colors.border};
    border-radius: 1.1rem;
    overflow: hidden;
    box-shadow: ${({ theme }) => theme.name === "light"
        ? "0 12px 28px rgba(15, 23, 42, 0.06)"
        : "0 16px 36px rgba(0, 0, 0, 0.32)"};

    @media (max-width: 1000px) {
        width: min(100%, 32rem);
    }

    @media (max-width: 600px) {
        border: none;
        border-radius: 0;
        box-shadow: none;
    }
`;

const Header = styled.div`
    position: relative;
    padding: 1.05rem 0.95rem 0.85rem;
    background: ${({ theme }) => getOnboardingContainerBg(theme)};
    text-align: center;

    &::after {
        content: "";
        position: absolute;
        left: 0.85rem;
        right: 0.85rem;
        bottom: 0;
        height: 1px;
        background: ${({ theme }) => theme.colors.border};
        opacity: 0.7;
    }

    @media (max-width: 600px) {
        padding: 0.95rem 0.75rem 0.75rem;
    }
`;

const BrandMark = styled.div`
    width: 2.4rem;
    height: 2.4rem;
    border-radius: 0.95rem;
    margin: 0 auto 0.55rem;
    display: flex;
    align-items: center;
    justify-content: center;
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    box-shadow: 0 8px 22px rgba(102, 126, 234, 0.28);
    color: #ffffff;
    font-size: 1.05rem;
    line-height: 1;
`;

const Eyebrow = styled.span`
    display: block;
    color: ${({ theme }) => theme.colors.subtleText};
    font-size: 0.62rem;
    font-weight: 600;
    letter-spacing: 0.08em;
    text-transform: uppercase;
`;

export const AuthStepPill = styled.span`
    color: ${({ theme }) => theme.colors.subtleText};
    font-size: 0.7rem;
    font-weight: 500;
`;

export const AuthTitle = styled.h1`
    margin: 0.25rem 0 0;
    color: ${({ theme }) => theme.colors.text};
    font-size: 1.18rem;
    line-height: 1.15;
    letter-spacing: -0.02em;
    font-weight: 600;
`;

export const AuthDescription = styled.p`
    margin: 0.3rem auto 0;
    color: ${({ theme }) => theme.colors.subtleText};
    font-size: 0.78rem;
    line-height: 1.5;
    max-width: 22rem;
`;

const TabsRow = styled.div`
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 0.4rem;
    padding: 0.8rem 0.85rem 0;
    background: ${({ theme }) => getOnboardingContainerBg(theme)};

    @media (max-width: 600px) {
        padding: 0.7rem 0.7rem 0;
    }
`;

const TabButton = styled.button`
    border: 1px solid ${({ theme, $active }) =>
        $active ? "transparent" : theme.colors.border};
    background: ${({ theme, $active }) =>
        $active
            ? "linear-gradient(135deg, #667eea 0%, #764ba2 100%)"
            : getOnboardingContainerBg(theme)};
    color: ${({ theme, $active }) =>
        $active ? "#ffffff" : theme.colors.subtleText};
    border-radius: 999px;
    padding: 0.55rem 0.7rem;
    font: inherit;
    font-size: 0.78rem;
    font-weight: 600;
    cursor: pointer;
    transition: background 0.18s ease, color 0.18s ease, border-color 0.18s ease, box-shadow 0.18s ease, transform 0.18s ease;
    box-shadow: ${({ $active }) =>
        $active ? "0 6px 16px rgba(102, 126, 234, 0.22)" : "none"};

    &:hover:not(:disabled) {
        color: ${({ theme, $active }) => ($active ? "#ffffff" : theme.colors.text)};
        border-color: ${({ theme, $active }) => ($active ? "transparent" : theme.colors.link)};
        ${({ $active }) =>
        $active
            ? "filter: brightness(1.05);"
            : ""}
    }

    &:focus-visible {
        outline: 2px solid ${({ theme }) => theme.colors.focusBlue || theme.colors.link};
        outline-offset: 2px;
    }
`;

export const AuthBody = styled.div`
    padding: 0.85rem;
    background: ${({ theme }) => getOnboardingContainerBg(theme)};

    @media (max-width: 600px) {
        padding: 0.8rem 0.7rem 0.85rem;
    }
`;

export const AuthStack = styled.div`
    display: flex;
    flex-direction: column;
    gap: 0.6rem;
`;

export const AuthPanel = styled.div`
    background: ${({ theme }) => getOnboardingContainerBg(theme)};
    border: 1px solid ${({ theme }) => theme.colors.border};
    border-radius: 0.9rem;
    padding: 0.85rem;
`;

export const AuthSubtlePanel = styled(AuthPanel)`
    background: ${({ theme }) => getTileBg(theme)};
`;

export const AuthLabel = styled.label`
    display: block;
    margin-bottom: 0.4rem;
    color: ${({ theme }) => theme.colors.text};
    font-size: 0.75rem;
    font-weight: 600;
`;

const fieldStyles = css`
    width: 100%;
    box-sizing: border-box;
    border: 1px solid ${({ theme }) => theme.colors.border};
    border-radius: 0.75rem;
    background: ${({ theme }) => getInputBg(theme)};
    color: ${({ theme }) => theme.colors.text};
    padding: 0.66rem 0.78rem;
    font: inherit;
    font-size: 0.8rem;
    line-height: 1.4;
    transition: background 0.16s ease, border-color 0.16s ease, box-shadow 0.16s ease;

    &::placeholder {
        color: ${({ theme }) => theme.colors.subtleText};
    }

    &:hover:not(:disabled) {
        background: ${({ theme }) => getInputHoverBg(theme)};
    }

    &:focus {
        outline: none;
        border-color: ${({ theme }) => theme.colors.focusBlue || theme.colors.link};
        box-shadow: 0 0 0 3px rgba(66, 133, 244, 0.16);
        background: ${({ theme }) => getInputHoverBg(theme)};
    }

    &:disabled {
        opacity: 0.65;
        cursor: not-allowed;
    }
`;

export const AuthInput = styled.input`
    ${fieldStyles}
`;

export const AuthTextArea = styled.textarea`
    ${fieldStyles}
    min-height: 6.5rem;
    resize: vertical;
    font-family: "SFMono-Regular", Menlo, Monaco, Consolas, "Liberation Mono", monospace;
`;

export const AuthHelperText = styled.p`
    margin: 0.45rem 0 0;
    color: ${({ theme }) => theme.colors.subtleText};
    font-size: 0.7rem;
    line-height: 1.45;
`;

export const AuthErrorMessage = styled.div`
    margin-top: 0.6rem;
    border-radius: 0.75rem;
    border: 1px solid ${({ theme }) => theme.colors.buttonDangerBorder || theme.colors.border};
    background: ${({ theme }) => theme.colors.buttonDangerBg || theme.colors.panelAlt};
    color: ${({ theme }) => theme.colors.text};
    padding: 0.65rem 0.75rem;
    font-size: 0.74rem;
    line-height: 1.4;
`;

export const AuthButtonRow = styled.div`
    display: flex;
    gap: 0.45rem;
    flex-wrap: wrap;
    margin-top: 0.7rem;

    > * {
        flex: 1 1 10rem;
    }

    @media (max-width: 600px) {
        flex-direction: column;
    }
`;

export const AuthLinkRow = styled.div`
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: center;
    gap: 0.3rem;
    color: ${({ theme }) => theme.colors.subtleText};
    font-size: 0.74rem;
    line-height: 1.45;
`;

export const AuthLink = styled.a`
    color: ${({ theme }) => theme.colors.link};
    text-decoration: none;
    font-weight: 600;

    &:hover {
        text-decoration: underline;
    }
`;

export const AuthTextButton = styled.button`
    padding: 0;
    border: none;
    background: none;
    color: ${({ theme }) => theme.colors.link};
    font: inherit;
    font-weight: 600;
    cursor: pointer;

    &:hover {
        text-decoration: underline;
    }
`;

export const AuthInlineBadge = styled.span`
    display: inline-flex;
    align-items: center;
    gap: 0.3rem;
    padding: 0.22rem 0.55rem;
    border-radius: 999px;
    background: ${({ theme }) => getTileBg(theme)};
    border: 1px solid ${({ theme }) => theme.colors.border};
    color: ${({ theme }) => theme.colors.text};
    font-size: 0.66rem;
    font-weight: 600;
`;

function AuthPageShell({
    activeTab,
    children,
    eyebrow = "Mirage account",
    title,
    description,
    showTabs = true,
    footer,
    icon = "✨",
}) {
    const navigate = useNavigate();

    const handleSelect = (tab) => {
        if (tab === activeTab) return;
        navigate(tab === "create" ? "/signup" : "/login");
    };

    return (
        <Shell>
            <Card>
                <Header>
                    <BrandMark aria-hidden="true">{icon}</BrandMark>
                    <Eyebrow>{eyebrow}</Eyebrow>
                    {title ? <AuthTitle>{title}</AuthTitle> : null}
                    {description ? <AuthDescription>{description}</AuthDescription> : null}
                </Header>

                {showTabs ? (
                    <TabsRow role="tablist" aria-label="Account access">
                        <TabButton
                            type="button"
                            role="tab"
                            aria-selected={activeTab === "create"}
                            $active={activeTab === "create"}
                            onClick={() => handleSelect("create")}
                        >
                            Create account
                        </TabButton>
                        <TabButton
                            type="button"
                            role="tab"
                            aria-selected={activeTab === "login"}
                            $active={activeTab === "login"}
                            onClick={() => handleSelect("login")}
                        >
                            Sign in
                        </TabButton>
                    </TabsRow>
                ) : null}

                <AuthBody>
                    {children}
                    {footer ? <div style={{ marginTop: "0.75rem", textAlign: "center" }}>{footer}</div> : null}
                </AuthBody>
            </Card>
        </Shell>
    );
}

export default AuthPageShell;
