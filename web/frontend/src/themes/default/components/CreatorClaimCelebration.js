import styled, { keyframes } from 'styled-components';
import { HiSparkles } from 'react-icons/hi2';
import { formatMirageCompact } from '../../../utils/formatters';
import { requireThemeColor } from '../../../utils/themeColor';

/**
 * Claim confirmation for creator rewards — `default` theme.
 *
 * Claiming is a chain transaction, so the only feedback the user got was the
 * generic "Transaction submitted" toast that every action produces. The money
 * arrived and nothing on screen said so. This overlay provides a clear
 * confirmation and reward summary.
 *
 * It is only rendered after the claim is projected on chain, so the amount it
 * shows is the confirmed one, never an optimistic guess.
 */

const confettiAnimation = keyframes`
    0% { transform: translateY(0) rotate(0deg); opacity: 1; }
    100% { transform: translateY(400px) rotate(720deg); opacity: 0; }
`;

const overlayFadeIn = keyframes`
    0% { opacity: 0; }
    100% { opacity: 1; }
`;

const cardPopIn = keyframes`
    0%   { opacity: 0; transform: translateY(12px) scale(0.94); }
    60%  { opacity: 1; transform: translateY(-2px) scale(1.01); }
    100% { opacity: 1; transform: translateY(0)    scale(1); }
`;

const emojiBob = keyframes`
    0%, 100% { transform: translateY(0) rotate(-4deg); }
    50%      { transform: translateY(-6px) rotate(4deg); }
`;

const Overlay = styled.div`
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.72);
    backdrop-filter: blur(6px);
    -webkit-backdrop-filter: blur(6px);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 10000;
    padding: 1.25rem;
    animation: ${overlayFadeIn} 0.25s ease;
`;

const Content = styled.div`
    position: relative;
    width: min(94vw, 480px);
    background: ${({ theme }) => requireThemeColor(theme, 'panel')};
    border: 1px solid ${({ theme }) => requireThemeColor(theme, 'border')};
    border-radius: 18px;
    padding: 1.6rem 1.75rem 1.25rem;
    text-align: center;
    overflow: hidden;
    box-shadow: 0 20px 60px rgba(0, 0, 0, 0.55);
    animation: ${cardPopIn} 0.45s cubic-bezier(0.2, 0.9, 0.3, 1.2);

    &::before {
        content: '';
        position: absolute;
        inset: 0 0 auto 0;
        height: 3px;
        background: linear-gradient(
            90deg,
            transparent 0%,
            ${({ theme }) => requireThemeColor(theme, 'followBtnBg')} 30%,
            ${({ theme }) => requireThemeColor(theme, 'followBtnBgHover')} 70%,
            transparent 100%
        );
    }
`;

const EmojiWrap = styled.div`
    margin: 0 auto 0.5rem;
    display: flex;
    align-items: center;
    justify-content: center;
`;

const Emoji = styled.div`
    font-size: 2.4rem;
    line-height: 1;
    animation: ${emojiBob} 1.6s ease-in-out infinite;
`;

const Eyebrow = styled.div`
    font-size: 0.62rem;
    font-weight: 600;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: ${({ theme }) => requireThemeColor(theme, 'followBtnBg')};
    margin-bottom: 0.3rem;
`;

const Title = styled.div`
    font-size: 1.15rem;
    font-weight: 800;
    color: ${({ theme }) => requireThemeColor(theme, 'text')};
    margin-bottom: 0.2rem;
    letter-spacing: -0.01em;
`;

const Subtitle = styled.div`
    font-size: 0.75rem;
    color: ${({ theme }) => requireThemeColor(theme, 'subtleText')};
    margin-bottom: 1rem;
`;

const RewardsList = styled.div`
    display: flex;
    flex-direction: column;
    gap: 0.4rem;
    margin-bottom: 1.1rem;
`;

const RewardRow = styled.div`
    display: flex;
    align-items: center;
    gap: 0.65rem;
    padding: 0.55rem 0.8rem;
    background: ${({ theme }) => requireThemeColor(theme, 'panelAlt')};
    border: 1px solid ${({ theme }) => requireThemeColor(theme, 'border')};
    border-radius: 10px;
    text-align: left;
`;

const RewardIcon = styled.div`
    width: 28px;
    height: 28px;
    border-radius: 7px;
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
    background: ${({ theme }) => requireThemeColor(theme, 'voteUpBg')};
    border: 0.5px solid ${({ theme }) => requireThemeColor(theme, 'voteUp')};
    color: ${({ theme }) => requireThemeColor(theme, 'voteUp')};

    svg {
        width: 16px;
        height: 16px;
    }
`;

const RewardMeta = styled.div`
    display: flex;
    flex-direction: column;
    flex: 1;
    min-width: 0;
`;

const RewardLabel = styled.div`
    font-size: 0.62rem;
    font-weight: 600;
    color: ${({ theme }) => requireThemeColor(theme, 'subtleText')};
    text-transform: uppercase;
    letter-spacing: 0.06em;
`;

const RewardValue = styled.div`
    font-family: ui-monospace, "SF Mono", "JetBrains Mono", "Menlo", "Monaco", Consolas, monospace;
    font-size: 0.92rem;
    font-weight: 500;
    letter-spacing: -0.01em;
    font-variant-numeric: tabular-nums;
    color: ${({ theme }) => requireThemeColor(theme, 'text')};
    line-height: 1.2;
`;

const CloseButton = styled.button`
    width: 100%;
    padding: 0.6rem 1.25rem;
    background: ${({ theme }) => requireThemeColor(theme, 'followBtnBg')};
    color: #ffffff;
    border: 1px solid ${({ theme }) => requireThemeColor(theme, 'followBtnBg')};
    border-radius: 9px;
    font-size: 0.8rem;
    font-weight: 700;
    font-family: inherit;
    cursor: pointer;
    transition: background 0.15s ease;

    &:hover {
        background: ${({ theme }) => requireThemeColor(theme, 'followBtnBgHover')};
    }

    &:focus-visible {
        outline: 2px solid ${({ theme }) => requireThemeColor(theme, 'focusBlue')};
        outline-offset: 2px;
    }
`;

const ConfettiPiece = styled.div`
    position: absolute;
    width: 10px;
    height: 10px;
    background: ${({ $color }) => $color};
    top: -10px;
    left: ${({ $left }) => $left}%;
    z-index: 2;
    pointer-events: none;
    animation: ${confettiAnimation} ${({ $duration }) => $duration}s linear forwards;
    animation-delay: ${({ $delay }) => $delay}s;
`;

const CONFETTI_COLORS = ['#f59e0b', '#22c55e', '#667eea', '#ec4899', '#764ba2'];

// Fixed so the pieces do not re-randomize on every parent render, which would
// restart the fall mid-animation.
const CONFETTI = Array.from({ length: 30 }, (_, i) => ({
    color: CONFETTI_COLORS[i % CONFETTI_COLORS.length],
    left: (i * 37) % 100,
    duration: 2 + ((i * 7) % 20) / 10,
    delay: ((i * 13) % 50) / 100,
}));

export default function CreatorClaimCelebration({ claimedUmirage, epochCount, onClose }) {
    return <Overlay onClick={onClose} role="dialog" aria-modal="true" aria-label="Creator rewards claimed">
        {CONFETTI.map((piece, i) => <ConfettiPiece
            key={i}
            $color={piece.color}
            $left={piece.left}
            $duration={piece.duration}
            $delay={piece.delay}
        />)}
        <Content onClick={(e) => e.stopPropagation()}>
            <EmojiWrap><Emoji>🎉</Emoji></EmojiWrap>
            <Eyebrow>Rewards Claimed</Eyebrow>
            <Title>Nice work!</Title>
            <Subtitle>
                {epochCount === 1
                    ? 'Your creator earnings have been added to your balance.'
                    : `Your creator earnings from ${epochCount} payout periods have been added to your balance.`}
            </Subtitle>
            <RewardsList>
                <RewardRow>
                    <RewardIcon aria-hidden="true"><HiSparkles /></RewardIcon>
                    <RewardMeta>
                        <RewardLabel>Mirage</RewardLabel>
                        <RewardValue>+{formatMirageCompact(String(claimedUmirage))} MIRAGE</RewardValue>
                    </RewardMeta>
                </RewardRow>
            </RewardsList>
            <CloseButton type="button" onClick={onClose}>Awesome</CloseButton>
        </Content>
    </Overlay>;
}
