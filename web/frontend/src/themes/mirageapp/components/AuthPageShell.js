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
        padding: 0.5rem 0 1rem;
    }

    @media (max-width: 600px) {
        padding: 0.4rem 0 0.8rem;
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
        width: min(100%, 32rem);
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

    & > svg {
        width: 1.4rem;
        height: 1.4rem;
    }
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

        > * {
            flex: 0 0 auto;
        }
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

const PalmTreeIcon = () => (
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 527.41 593.64" fill="#ffffff">
        <path d="M85.03,197.11c-.77-.41-1.02,1.23-1.27,1.98-.89,4.66-1.97,9.3-2.97,13.74-4.2,16.58-.74,36.06-12.57,49.79-19.98,21.05-35.86,46.61-49.24,72.25-2.54,4.08-5,14.71-9.37,11.16-10.87-20.06-10.77-56.33-8.13-80.05,8.11-74.35,64.71-133.17,140.39-137.47,25.49-1.82,51.61,1.9,75.05,12.03,4.28,1.83,3.56-.9,1.44-3.38-14.47-18.53-32.09-34.46-50.45-48.97-6.85-5.97,2.67-9.75,4.16-15.29-.57-2.2-4.03-.86-6.05-.95-5.01.31-11.57.58-15.54-.33-9.76-3.12-17.1-10.88-26.25-15.46-2.83-1.81-7.17-3.15-8.24-6.48-.16-4.05,3.86-8.93,5.99-12.27,4.72-5.67.85-5.42-4.33-3.97-6.1,1.49-12.2,4.27-18.51,4.21-8.89-.62-19.71-5.44-28.83-7.13-10.53-2.21-21.48-3.4-32.19-4.48-1.55-.15-3.18-.2-4.71-.48-1.54-.26-2.54-.96-2.43-1.92.18-1.21,1.22-2.15,2.13-2.92,12.76-9.25,31.39-14.68,45.47-17.65,87.21-17.38,152.37,47.81,181.95,123.22.62.03,1.13-1.02,1.55-2.36.56-1.92,1.07-3.92,1.74-5.79C288.75,45.92,362.99-15.54,441.97,3.5c13.15,2.8,26.57,8.26,38.43,14.69,3.05,2.01,5.62,3.08,6.83,5.59.2.77-.49,1.33-1.99,1.58-1.8.29-4.39.29-6.49.37-27.45.93-54.01,10.14-75.58,27.36-5.24,4.36-12.11,1.67-18.25.55-3.09-.75-6.54-.66-10.08-.72-2.63.05-6.46-.29-8.81.48-.61.3-.68.76-.27,1.32,3.71,3.17,10.62,6.8,13.43,10.29,1.92,2.1.07,4.3-1.96,5.72-27.33,20.52-55.82,41.74-78,68.06-3.59,4.29-1.27,4.95,3.04,2.8,101.2-46.59,244.69,12.48,222.91,138.05-1.12,4.66-2.51,9.22-4.48,13.59-1.59,3.35-3.35,5.73-7.15,2.78-8.67-6.91-16.19-15.31-24-23.21-13.03-13.67-27.22-26.21-42.42-37.49-9.29-6.31-15.87-10.04-16.58-22.27-1.12-8.18-3.49-16.18-5.39-24.18-.61-2.73-1.76-3.87-3.15-.85-2.97,5.04-4.39,22.37-9.19,23.78-4.76.73-8.88-4.31-13.09-6-39.7-21.77-83.93-26.94-128.72-25.07-4.85.08-6.56,4.21-7.78,8.3-39.34,131.64-2.05,288.21,88.55,390.43,5.01,4.53,6.1,11.99-3.63,13.79-35.93.13-72.02.82-107.94-.04-9-.37-19.77,1.45-23.34-9.2-21.22-77.97-26.49-159.48-23.41-240.19,1.04-22.78,3.56-45.49,8.02-67.89,6.36-31.78,16.54-63.02,32.21-91.36,2.95-4.91-2.26-4.82-5.58-4.85-8.36-.08-17.58.72-26.01,1.57-38.68,4.18-71.21,22.85-100.3,47.6-2.41,1.7-5.2,5.72-8.19,5.7-2.89-1.86-2.41-6.9-3.35-9.94-1.36-7.2-2.46-14.46-3.74-21.64-.48-1.8-.37-4.37-1.43-5.85l-.05-.05Z"/>
    </svg>
);

function AuthPageShell({
    activeTab,
    children,
    eyebrow = "Mirage account",
    title,
    description,
    showTabs = true,
    footer,
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
                    <BrandMark aria-hidden="true"><PalmTreeIcon /></BrandMark>
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
