import { useMemo, useState } from 'react';
import styled from 'styled-components';
import { Link } from 'react-router-dom';
import { HiOutlineBanknotes, HiOutlineArrowUp, HiOutlineChatBubbleLeft } from 'react-icons/hi2';
import Storage from '../../../utils/Storage';
import { formatMirageCompact } from '../../../utils/formatters';
import { useCreatorEarnings } from '../../../logic/useCreatorEarnings';
import { requireThemeColor } from '../../../utils/themeColor';
import CreatorClaimCelebration from './CreatorClaimCelebration';

/**
 * Claimable creator rewards, as a feed card — `default` theme.
 *
 * Creator rewards expire and are burned, so they cannot only live on a tab of
 * your own profile: a user who never opens that tab loses the money. This sits
 * at the top of the home and following feeds and disappears once there is
 * nothing left to claim.
 *
 * The card uses a header (icon tile, title, right-aligned amount pill) over
 * a body of reward rows and a full-width CTA.
 * The rows list the posts the money came from, so the number in the header is
 * accounted for rather than asserted. Colors go through tokens rather than the
 * raw hex that card inlined (RULES.md R213).
 *
 * The claim deadline is deliberately not here. It is per-epoch, so on a card
 * that batches several it can only ever show one of them; the Earnings tab
 * lists the real deadline against each period.
 */

// Matches the post CardView (`width: 100%`, `margin: 4px 0`, 8px radius) so the
// card lines up with the feed column below it and shares the same background.
const CardContainer = styled.div`
    box-sizing: border-box;
    width: 100%;
    max-width: 100%;
    align-self: flex-start;
    margin: 4px 0;
    background: ${({ theme }) => requireThemeColor(theme, 'bg')};
    border: 1px solid ${({ theme }) => requireThemeColor(theme, 'border')};
    border-radius: 8px;
    overflow: hidden;

    @media (max-width: 600px) {
        border-radius: 6px;
    }
`;

const Header = styled.div`
    box-sizing: border-box;
    width: 100%;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.5rem;
    padding: 0.4rem 1rem;

    @media (max-width: 600px) {
        padding: 0.35rem 0.85rem;
    }
`;

const TitleRow = styled.div`
    display: flex;
    align-items: center;
    gap: 0.4rem;
    flex: 1;
    min-width: 0;
`;

const IconTile = styled.div`
    flex-shrink: 0;
    width: 24px;
    height: 24px;
    border-radius: 7px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    line-height: 1;
    color: ${({ theme }) => requireThemeColor(theme, 'gradientStart')};

    svg {
        width: 0.8rem;
        height: 0.8rem;
    }
`;

const TitleText = styled.div`
    flex: 1;
    min-width: 0;
    font-size: 0.72rem;
    font-weight: 600;
    color: ${({ theme }) => requireThemeColor(theme, 'text')};
    line-height: 1.2;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
`;

const HeaderBadge = styled.span`
    flex-shrink: 0;
    display: inline-flex;
    align-items: center;
    font-size: 0.55rem;
    font-weight: 700;
    padding: 0.12rem 0.4rem;
    border-radius: 999px;
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
    color: ${({ theme }) => requireThemeColor(theme, 'voteUp')};
    background: ${({ theme }) => requireThemeColor(theme, 'voteUpBg')};
`;

const Body = styled.div`
    padding: 0 1rem 0.6rem;
    display: flex;
    flex-direction: column;
    gap: 0.45rem;

    @media (max-width: 600px) {
        padding: 0 0.85rem 0.55rem;
    }
`;

const RewardsList = styled.div`
    display: flex;
    flex-direction: column;
    gap: 0.4rem;
`;

const RewardRow = styled(Link)`
    display: flex;
    align-items: center;
    gap: 0.65rem;
    padding: 0.55rem 0.8rem;
    background: ${({ theme }) => requireThemeColor(theme, 'panelAlt')};
    border: 1px solid ${({ theme }) => requireThemeColor(theme, 'border')};
    border-radius: 10px;
    text-align: left;
    text-decoration: none;
    transition: border-color 0.15s ease;

    &:hover {
        border-color: ${({ theme }) => requireThemeColor(theme, 'gradientStart')};
        text-decoration: none;
    }

    &:focus-visible {
        outline: 2px solid ${({ theme }) => requireThemeColor(theme, 'focusBlue')};
        outline-offset: 2px;
    }
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
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
`;

const RewardTitle = styled.div`
    font-size: 0.7rem;
    font-weight: 500;
    color: ${({ theme }) => requireThemeColor(theme, 'text')};
    line-height: 1.3;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
`;

const RewardValue = styled.div`
    flex-shrink: 0;
    font-family: ui-monospace, "SF Mono", "JetBrains Mono", "Menlo", "Monaco", Consolas, monospace;
    font-size: 0.82rem;
    font-weight: 500;
    letter-spacing: -0.01em;
    font-variant-numeric: tabular-nums;
    color: ${({ theme }) => requireThemeColor(theme, 'text')};
    line-height: 1.2;
`;

const CtaButton = styled.button`
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 100%;
    padding: 0.42rem 0.75rem;
    border-radius: 7px;
    font-size: 0.68rem;
    font-weight: 700;
    font-family: inherit;
    color: #fff;
    border: none;
    cursor: pointer;
    background: ${({ theme }) => requireThemeColor(theme, 'followBtnBg')};
    transition: background 0.15s ease, transform 0.15s ease;

    &:hover:not(:disabled) {
        background: ${({ theme }) => requireThemeColor(theme, 'followBtnBgHover')};
        transform: translateY(-1px);
    }

    &:active:not(:disabled) {
        transform: translateY(0);
    }

    &:disabled {
        opacity: 0.5;
        cursor: not-allowed;
    }

    &:focus-visible {
        outline: 2px solid ${({ theme }) => requireThemeColor(theme, 'focusBlue')};
        outline-offset: 2px;
    }
`;

const ClaimErrorMessage = styled.div`
    padding: 0.45rem 0.65rem;
    border-radius: 8px;
    font-size: 0.68rem;
    line-height: 1.35;
    color: ${({ theme }) => requireThemeColor(theme, 'voteDown')};
    background: ${({ theme }) => requireThemeColor(theme, 'buttonDangerBg')};
    border: 1px solid ${({ theme }) => requireThemeColor(theme, 'buttonDangerBorder')};
`;

// Top earners only. The card is a prompt to claim, not the ledger; the Earnings
// tab is where the full history belongs.
const MAX_ROWS = 3;

/** A post can earn across several epochs, so the rows are summed per post. */
function mergePosts(epochs) {
    const merged = new Map();
    for (const epoch of epochs) {
        for (const post of epoch.posts) {
            const current = merged.get(post.txhash);
            if (current) {
                current.amount += BigInt(post.amount);
                current.upvotes += Number(post.upvote_units);
                current.replies += Number(post.direct_reply_units);
                continue;
            }
            merged.set(post.txhash, {
                txhash: post.txhash,
                amount: BigInt(post.amount),
                upvotes: Number(post.upvote_units),
                replies: Number(post.direct_reply_units),
                title: post.title,
                excerpt: post.excerpt,
                community: post.community,
                isComment: post.is_comment,
                deleted: post.deleted,
            });
        }
    }
    return [...merged.values()].sort((a, b) => (b.amount > a.amount ? 1 : b.amount < a.amount ? -1 : 0));
}

function engagementLabel(post) {
    const parts = [];
    if (post.upvotes) parts.push(`${post.upvotes} upvote${post.upvotes === 1 ? '' : 's'}`);
    if (post.replies) parts.push(`${post.replies} repl${post.replies === 1 ? 'y' : 'ies'}`);
    return [post.community ? `c/${post.community}` : null, ...parts].filter(Boolean).join(' · ');
}

export default function CreatorEarningsBanner() {
    const address = String(Storage.load('publicKey', '') || '').toLowerCase();
    const earnings = useCreatorEarnings(address);
    const [claiming, setClaiming] = useState(false);
    const [claimed, setClaimed] = useState(null);
    const [submittedEpochs, setSubmittedEpochs] = useState([]);

    const batch = useMemo(() => {
        if (!earnings.maxClaimEpochs) return [];
        return earnings.claimable
            .filter((item) => !submittedEpochs.includes(Number(item.epoch_id)))
            .sort((a, b) => (
                Number(a.claim_deadline_unix) - Number(b.claim_deadline_unix)
                || Number(a.epoch_id) - Number(b.epoch_id)
            ))
            .slice(0, earnings.maxClaimEpochs);
    }, [earnings.claimable, earnings.maxClaimEpochs, submittedEpochs]);
    const posts = useMemo(() => mergePosts(batch), [batch]);

    // A confirmed claim empties `claimable`, so the celebration has to be able
    // to outlive the card that started it.
    if (claimed) {
        return <CreatorClaimCelebration
            claimedUmirage={claimed.umirage}
            epochCount={claimed.epochCount}
            onClose={() => setClaimed(null)}
        />;
    }
    if (!address || !batch.length) return null;

    const total = batch.reduce((sum, item) => sum + (BigInt(item.earned) - BigInt(item.claimed)), 0n);
    const epochIds = batch.map((item) => Number(item.epoch_id));
    const rows = posts.slice(0, MAX_ROWS);

    return <CardContainer role="region" aria-label="Creator rewards ready to claim">
        <Header>
            <TitleRow>
                <IconTile aria-hidden="true"><HiOutlineBanknotes /></IconTile>
                <TitleText>Creator earnings</TitleText>
            </TitleRow>
            <HeaderBadge>{formatMirageCompact(String(total))} MIRAGE</HeaderBadge>
        </Header>
        <Body>
            {rows.length > 0 && <RewardsList>
                {rows.map((post) => <RewardRow key={post.txhash} to={`/p/${post.txhash}`}>
                    <RewardIcon aria-hidden="true">
                        {post.upvotes >= post.replies ? <HiOutlineArrowUp /> : <HiOutlineChatBubbleLeft />}
                    </RewardIcon>
                    <RewardMeta>
                        <RewardLabel>{engagementLabel(post)}</RewardLabel>
                        <RewardTitle>
                            {post.deleted
                                ? 'Deleted post'
                                : post.title || post.excerpt || (post.isComment ? 'Your comment' : 'Your post')}
                        </RewardTitle>
                    </RewardMeta>
                    <RewardValue>{formatMirageCompact(String(post.amount))}</RewardValue>
                </RewardRow>)}
            </RewardsList>}
            {earnings.error && <ClaimErrorMessage>{earnings.error}</ClaimErrorMessage>}
            <CtaButton
                type="button"
                disabled={earnings.pending || claiming}
                onClick={async () => {
                    setClaiming(true);
                    try {
                        await earnings.claim(epochIds);
                        setSubmittedEpochs((current) => [...current, ...epochIds]);
                        setClaimed({ umirage: total.toString(), epochCount: epochIds.length });
                    } catch (_) {
                        // `claim` already surfaced the reason through earnings.error.
                    } finally {
                        setClaiming(false);
                    }
                }}
            >
                {earnings.pendingStatus || 'Claim rewards'}
            </CtaButton>
        </Body>
    </CardContainer>;
}
