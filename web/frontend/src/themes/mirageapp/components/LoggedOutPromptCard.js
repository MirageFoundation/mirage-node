import React from "react";
import styled from "styled-components";
import Button from "./Button.js";

const UsersIcon = () => (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" />
        <circle cx="9" cy="7" r="4" />
        <path d="M22 21v-2a4 4 0 0 0-3-3.87" />
        <path d="M16 3.13a4 4 0 0 1 0 7.75" />
    </svg>
);

const PulseIcon = () => (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <path d="M22 12h-4l-3 9L9 3l-3 9H2" />
    </svg>
);

const SparkleIcon = () => (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <path d="M12 3v3" />
        <path d="M12 18v3" />
        <path d="M5.6 5.6l2.1 2.1" />
        <path d="M16.3 16.3l2.1 2.1" />
        <path d="M3 12h3" />
        <path d="M18 12h3" />
        <path d="M5.6 18.4l2.1-2.1" />
        <path d="M16.3 7.7l2.1-2.1" />
    </svg>
);

const STAT_TONES = [
    {
        Icon: UsersIcon,
        color: "#667eea",
        badgeBg: "rgba(102, 126, 234, 0.18)",
        tint: "rgba(102, 126, 234, 0.16)",
    },
    {
        Icon: PulseIcon,
        color: "#10b981",
        badgeBg: "rgba(16, 185, 129, 0.18)",
        tint: "rgba(16, 185, 129, 0.16)",
    },
    {
        Icon: SparkleIcon,
        color: "#f59e0b",
        badgeBg: "rgba(245, 158, 11, 0.20)",
        tint: "rgba(245, 158, 11, 0.18)",
    },
];

const Card = styled.section`
    width: min(60%, 30rem);
    margin: 0.6rem auto 0;
    padding: 1.05rem 0.95rem 0.95rem;
    border-radius: 1.1rem;
    border: 1px solid ${({ theme }) => theme.colors.border};
    background: ${({ theme }) => theme.name === "light" ? "#FFFFFF" : "rgb(25, 28, 31)"};
    box-sizing: border-box;
    text-align: center;
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

const Title = styled.h2`
    margin: 0.25rem 0 0;
    color: ${({ theme }) => theme.colors.text};
    font-size: 1.18rem;
    line-height: 1.15;
    letter-spacing: -0.02em;
    font-weight: 600;
`;

const Description = styled.p`
    margin: 0.4rem auto 0;
    color: ${({ theme }) => theme.colors.subtleText};
    font-size: 0.78rem;
    line-height: 1.55;
    max-width: 26rem;
`;

const NoticePill = styled.div`
    display: inline-flex;
    align-items: center;
    gap: 0.35rem;
    margin: 0.55rem auto 0;
    padding: 0.22rem 0.6rem;
    border-radius: 999px;
    background: rgba(245, 158, 11, 0.14);
    border: 1px solid rgba(245, 158, 11, 0.35);
    color: #d97706;
    font-size: 0.6rem;
    font-weight: 600;
    letter-spacing: 0.04em;
    text-transform: uppercase;

    &::before {
        content: "";
        width: 0.35rem;
        height: 0.35rem;
        border-radius: 999px;
        background: #f59e0b;
        box-shadow: 0 0 0 0.18rem rgba(245, 158, 11, 0.25);
    }
`;

const LinksRow = styled.div`
    display: flex;
    flex-wrap: wrap;
    justify-content: center;
    align-items: center;
    gap: 0.25rem 0.5rem;
    margin-top: 0.6rem;
    color: ${({ theme }) => theme.colors.subtleText};
    font-size: 0.72rem;
    line-height: 1.45;
    word-break: break-word;

    a {
        color: ${({ theme }) => theme.colors.link};
        font-weight: 500;
        text-decoration: none;
    }

    a:hover {
        text-decoration: underline;
    }
`;

const StatsGrid = styled.div`
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 0.5rem;
    margin-top: 0.85rem;

    @media (max-width: 480px) {
        gap: 0.4rem;
    }
`;

const StatTile = styled.div`
    min-width: 0;
    position: relative;
    padding: 0.7rem 0.55rem 0.65rem;
    border-radius: 0.85rem;
    border: 1px solid ${({ theme }) => theme.colors.border};
    background: ${({ theme }) => theme.name === "light"
        ? "linear-gradient(180deg, #ffffff 0%, rgb(248, 249, 252) 100%)"
        : "linear-gradient(180deg, rgb(44, 50, 54) 0%, rgb(36, 39, 45) 100%)"};
    text-align: center;
    overflow: hidden;
    transition: transform 0.18s ease, box-shadow 0.18s ease;

    &::before {
        content: "";
        position: absolute;
        inset: 0;
        border-radius: inherit;
        pointer-events: none;
        background: radial-gradient(120% 80% at 50% 0%, ${({ $tint }) => $tint || "rgba(102, 126, 234, 0.18)"} 0%, transparent 60%);
        opacity: 0.9;
    }

    &:hover {
        transform: translateY(-1px);
        box-shadow: 0 10px 22px ${({ $tint }) => $tint || "rgba(102, 126, 234, 0.18)"};
    }
`;

const StatIconBadge = styled.div`
    position: relative;
    width: 1.7rem;
    height: 1.7rem;
    margin: 0 auto 0.4rem;
    display: flex;
    align-items: center;
    justify-content: center;
    border-radius: 999px;
    background: ${({ $bg }) => $bg || "rgba(102, 126, 234, 0.18)"};
    color: ${({ $color }) => $color || "#667eea"};

    svg {
        width: 0.95rem;
        height: 0.95rem;
    }
`;

const StatValue = styled.div`
    position: relative;
    color: ${({ theme }) => theme.colors.text};
    font-size: 1.05rem;
    line-height: 1.1;
    font-weight: 700;
    font-variant-numeric: tabular-nums;
    letter-spacing: -0.02em;
`;

const StatLabel = styled.div`
    position: relative;
    margin-top: 0.22rem;
    color: ${({ theme }) => theme.colors.subtleText};
    font-size: 0.6rem;
    line-height: 1.25;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    font-weight: 600;
`;

const InviteText = styled.div`
    margin-top: 0.8rem;
    color: ${({ theme }) => theme.colors.text};
    font-size: 0.74rem;
    line-height: 1.4;
    font-weight: 500;
`;

const ActionRow = styled.div`
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 0.45rem;
    margin-top: 0.55rem;

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

const PalmTreeIcon = () => (
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 527.41 593.64" fill="#ffffff">
        <path d="M85.03,197.11c-.77-.41-1.02,1.23-1.27,1.98-.89,4.66-1.97,9.3-2.97,13.74-4.2,16.58-.74,36.06-12.57,49.79-19.98,21.05-35.86,46.61-49.24,72.25-2.54,4.08-5,14.71-9.37,11.16-10.87-20.06-10.77-56.33-8.13-80.05,8.11-74.35,64.71-133.17,140.39-137.47,25.49-1.82,51.61,1.9,75.05,12.03,4.28,1.83,3.56-.9,1.44-3.38-14.47-18.53-32.09-34.46-50.45-48.97-6.85-5.97,2.67-9.75,4.16-15.29-.57-2.2-4.03-.86-6.05-.95-5.01.31-11.57.58-15.54-.33-9.76-3.12-17.1-10.88-26.25-15.46-2.83-1.81-7.17-3.15-8.24-6.48-.16-4.05,3.86-8.93,5.99-12.27,4.72-5.67.85-5.42-4.33-3.97-6.1,1.49-12.2,4.27-18.51,4.21-8.89-.62-19.71-5.44-28.83-7.13-10.53-2.21-21.48-3.4-32.19-4.48-1.55-.15-3.18-.2-4.71-.48-1.54-.26-2.54-.96-2.43-1.92.18-1.21,1.22-2.15,2.13-2.92,12.76-9.25,31.39-14.68,45.47-17.65,87.21-17.38,152.37,47.81,181.95,123.22.62.03,1.13-1.02,1.55-2.36.56-1.92,1.07-3.92,1.74-5.79C288.75,45.92,362.99-15.54,441.97,3.5c13.15,2.8,26.57,8.26,38.43,14.69,3.05,2.01,5.62,3.08,6.83,5.59.2.77-.49,1.33-1.99,1.58-1.8.29-4.39.29-6.49.37-27.45.93-54.01,10.14-75.58,27.36-5.24,4.36-12.11,1.67-18.25.55-3.09-.75-6.54-.66-10.08-.72-2.63.05-6.46-.29-8.81.48-.61.3-.68.76-.27,1.32,3.71,3.17,10.62,6.8,13.43,10.29,1.92,2.1.07,4.3-1.96,5.72-27.33,20.52-55.82,41.74-78,68.06-3.59,4.29-1.27,4.95,3.04,2.8,101.2-46.59,244.69,12.48,222.91,138.05-1.12,4.66-2.51,9.22-4.48,13.59-1.59,3.35-3.35,5.73-7.15,2.78-8.67-6.91-16.19-15.31-24-23.21-13.03-13.67-27.22-26.21-42.42-37.49-9.29-6.31-15.87-10.04-16.58-22.27-1.12-8.18-3.49-16.18-5.39-24.18-.61-2.73-1.76-3.87-3.15-.85-2.97,5.04-4.39,22.37-9.19,23.78-4.76.73-8.88-4.31-13.09-6-39.7-21.77-83.93-26.94-128.72-25.07-4.85.08-6.56,4.21-7.78,8.3-39.34,131.64-2.05,288.21,88.55,390.43,5.01,4.53,6.1,11.99-3.63,13.79-35.93.13-72.02.82-107.94-.04-9-.37-19.77,1.45-23.34-9.2-21.22-77.97-26.49-159.48-23.41-240.19,1.04-22.78,3.56-45.49,8.02-67.89,6.36-31.78,16.54-63.02,32.21-91.36,2.95-4.91-2.26-4.82-5.58-4.85-8.36-.08-17.58.72-26.01,1.57-38.68,4.18-71.21,22.85-100.3,47.6-2.41,1.7-5.2,5.72-8.19,5.7-2.89-1.86-2.41-6.9-3.35-9.94-1.36-7.2-2.46-14.46-3.74-21.64-.48-1.8-.37-4.37-1.43-5.85l-.05-.05Z"/>
    </svg>
);

export default function LoggedOutPromptCard({
    eyebrow = "Welcome to Mirage",
    title,
    description,
    notice,
    stats = [],
    links = [],
    inviteText = "Have an invite code? Join the community today.",
    primaryLabel = "Create account",
    primaryTo = "/signup",
    secondaryLabel = "Sign in",
    secondaryTo = "/login",
    children,
    ...props
}) {
    return (
        <Card {...props}>
            <BrandMark aria-hidden="true"><PalmTreeIcon /></BrandMark>
            {eyebrow ? <Eyebrow>{eyebrow}</Eyebrow> : null}
            {title ? <Title>{title}</Title> : null}
            {notice ? (
                <div style={{ textAlign: "center" }}>
                    <NoticePill>{notice}</NoticePill>
                </div>
            ) : null}
            {description ? <Description>{description}</Description> : null}

            {links.length > 0 ? (
                <LinksRow>
                    {links.map((link, index) => (
                        <React.Fragment key={link.label}>
                            <a href={link.href} target={link.external ? "_blank" : undefined} rel={link.external ? "noopener noreferrer" : undefined}>
                                {link.label}
                            </a>
                            {index < links.length - 1 ? <span aria-hidden="true">·</span> : null}
                        </React.Fragment>
                    ))}
                </LinksRow>
            ) : null}

            {stats.length > 0 ? (
                <StatsGrid>
                    {stats.map((stat, index) => {
                        const tone = STAT_TONES[index % STAT_TONES.length];
                        const Icon = stat.icon || tone.Icon;
                        return (
                            <StatTile key={stat.label} $tint={tone.tint}>
                                <StatIconBadge $bg={tone.badgeBg} $color={tone.color}>
                                    <Icon />
                                </StatIconBadge>
                                <StatValue>{stat.value}</StatValue>
                                <StatLabel>{stat.label}</StatLabel>
                            </StatTile>
                        );
                    })}
                </StatsGrid>
            ) : null}

            {children}

            {inviteText ? <InviteText>{inviteText}</InviteText> : null}

            <ActionRow>
                <PrimaryButton to={primaryTo} size="sm" fullWidth mobileFullWidth>
                    {primaryLabel}
                </PrimaryButton>
                <SecondaryButton to={secondaryTo} size="sm" fullWidth mobileFullWidth>
                    {secondaryLabel}
                </SecondaryButton>
            </ActionRow>
        </Card>
    );
}
