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
        border: none;
        border-radius: 0;
        box-shadow: none;
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
    emoji = "✨",
    children,
    ...props
}) {
    return (
        <Card {...props}>
            <BrandMark aria-hidden="true">{emoji}</BrandMark>
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
