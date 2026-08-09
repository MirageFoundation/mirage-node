import React from "react";
import styled, { css, keyframes } from "styled-components";
import { useVoteHandler, resolveDirection, computeDisplayVotes } from '../../../logic/useVote';

/**
 * VoteSection — mobile-app inspired PostActions pill.
 *
 * Modes:
 *  - inline (default when used in CardView action row) → horizontal pill
 *      [▲  count  ▼]
 *    with rounded container, subtle border, dividers, color on active state.
 *  - column (used in comment lists) → vertical stack
 *      [+/-]  ▲  count  ▼
 *
 * Press animation uses CSS transform (`scale(0.9)` on :active) so it does
 * not cause any layout thrash.
 */

const bounceUp = keyframes`
    0%   { transform: translateY(0); }
    50%  { transform: translateY(-3px); }
    100% { transform: translateY(0); }
`;

const bounceDown = keyframes`
    0%   { transform: translateY(0); }
    50%  { transform: translateY(3px); }
    100% { transform: translateY(0); }
`;

// ─── Inline pill ───────────────────────────────────────────────────────────

/* Inline vote pill
 * ─ Container bg matches the share/block icon chips (`actionIconBg`).
 * ─ No border (the tinted surface already separates it from the card bg).
 * ─ Fixed 32px height so it lines up with the comment pill + action chips.
 * ─ Root has NO hover state; only the individual arrow buttons change bg on
 *   hover so hovering the upvote tint doesn't light up the whole pill. */
const PillRoot = styled.div`
    display: inline-flex;
    align-items: center;
    height: 32px;
    padding: 0;
    border-radius: 9999px;
    border: none;
    background: ${({ theme }) => theme.colors.actionIconBg};
    color: ${({ theme }) => theme.colors.text};
    font-weight: 600;
    font-size: 0.66rem;
    line-height: 1;
    overflow: hidden;
`;

const PillDivider = styled.span`
    display: none;
`;

const PillButton = styled.button`
    appearance: none;
    background: transparent;
    border: none;
    padding: 0 10px;
    margin: 0;
    cursor: pointer;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    color: ${({ $active, $up, theme }) =>
        $active
            ? ($up ? theme.colors.voteUp : theme.colors.voteDown)
            : theme.colors.text};
    font: inherit;
    font-weight: 600;
    height: 100%;
    line-height: 1;
    /* Only animate color + background; no transform so the glyph doesn't
     * shift on hover/press (requested UX). */
    transition: color 0.12s ease, background 0.12s ease;

    &:disabled {
        cursor: default;
    }

    &:hover:not(:disabled) {
        /* Only the arrow cell's background highlights, not the full pill. */
        background: ${({ theme }) => theme.colors.actionIconHoverBg};
        color: ${({ $up, theme }) => ($up ? theme.colors.voteUp : theme.colors.voteDown)};
    }

    svg {
        display: block;
        width: 18px;
        height: 18px;
        fill: currentColor;
    }

    ${({ $bouncing, $up }) =>
        $bouncing &&
        css`
            svg {
                animation: ${$up ? bounceUp : bounceDown} 0.3s ease-out;
            }
        `}
`;

const PillCount = styled.span`
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-width: 1.1rem;
    padding: 0 6px;
    font: inherit;
    /* Slightly smaller + lighter than the arrows so the number reads as
     * metadata rather than a button label. */
    font-size: 0.62rem;
    font-weight: 500;
    line-height: 1;
    color: ${({ $up, $down, theme }) =>
        $up
            ? theme.colors.voteUp
            : $down
                ? theme.colors.voteDown
                : theme.colors.text};
`;

// ─── Column (comment) mode ─────────────────────────────────────────────────

const VoteColumn = styled.div`
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 0;
    align-self: flex-start;
`;

const ColumnButton = styled.button`
    appearance: none;
    background: transparent;
    border: none;
    padding: 0;
    margin: 0;
    cursor: pointer;
    color: ${({ $active, $up, theme }) =>
        $active
            ? ($up ? theme.colors.voteUp : theme.colors.voteDown)
            : theme.colors.subtleText};
    display: inline-flex;
    align-items: center;
    justify-content: center;
    line-height: 0;
    width: 28px;
    height: 24px;
    transition: color 0.12s ease, transform 0.12s ease;

    &:disabled {
        cursor: default;
    }

    &:hover:not(:disabled) {
        color: ${({ $up, theme }) => ($up ? theme.colors.voteUp : theme.colors.voteDown)};
    }

    &:active:not(:disabled) {
        transform: scale(0.9);
    }

    svg {
        display: block;
        width: 20px;
        height: 20px;
        fill: currentColor;
    }
`;

const ColumnCount = styled.div`
    font-size: 0.68rem;
    font-weight: 700;
    color: ${({ theme }) => theme.colors.text};
    line-height: 1;
    text-align: center;
    padding: 0;
`;

const CollapseToggle = styled.span`
    display: inline-flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    color: ${({ theme }) => theme.colors.subtleText};
    font-size: 0.55rem;
    font-weight: bold;
    padding: 0 0.1rem;
    line-height: 1em;
    height: 1em;
    user-select: none;
    &:hover { color: ${({ theme }) => theme.colors.text}; }
`;

// ─── Icons ─────────────────────────────────────────────────────────────────

// Triangle icons ported from bluemoon/VoteSection so both themes share the
// same up/down glyph language.
const UpIcon = (props) => (
    <svg viewBox="0 0 16 16" width="1em" height="1em" aria-hidden="true" focusable="false" {...props}>
        <path d="M8 3l5 8H3l5-8z" fill="currentColor" />
    </svg>
);

const DownIcon = (props) => (
    <svg viewBox="0 0 16 16" width="1em" height="1em" aria-hidden="true" focusable="false" {...props}>
        <path d="M8 13l-5-8h10l-5 8z" fill="currentColor" />
    </svg>
);

// ─── Component ─────────────────────────────────────────────────────────────

function DefaultVoteSection({ state, post, updatePost, showToggle = true, inline = false }) {
    const { handleVote, isPending, isLocallyPending, formatVoteStatus } = useVoteHandler({ state, updatePost });

    const direction = resolveDirection(post, state);
    const displayVotes = computeDisplayVotes(post, direction);
    const hasPendingVote = isPending(post.post_id) || isLocallyPending(post.post_id);
    const voteStatus = hasPendingVote ? formatVoteStatus(post.post_id) : null;
    const upActive = direction === +1;
    const downActive = direction === -1;

    const [bounce, setBounce] = React.useState(null);
    const bounceTimerRef = React.useRef(null);
    React.useEffect(() => () => {
        if (bounceTimerRef.current) clearTimeout(bounceTimerRef.current);
    }, []);
    const onClick = (dir) => (e) => {
        // Fire the vote synchronously first so the network request is not
        // blocked behind a React state flush (this is what made default
        // feel ~1s slower than bluemoon).
        handleVote(post, dir);
        // Drop focus so the hover/focus tint clears immediately, matching
        // bluemoon's _voteClick behavior.
        if (e && e.currentTarget) e.currentTarget.blur();
        // Schedule the bounce after the click work is dispatched.
        if (bounceTimerRef.current) clearTimeout(bounceTimerRef.current);
        setBounce(dir);
        bounceTimerRef.current = setTimeout(() => {
            bounceTimerRef.current = null;
            setBounce(null);
        }, 320);
    };

    if (inline) {
        return (
            <PillRoot>
                <PillButton
                    $up
                    $active={upActive}
                    $bouncing={bounce === +1}
                    disabled={hasPendingVote} title={voteStatus || undefined} aria-busy={hasPendingVote}
                    onClick={onClick(+1)}
                    aria-label="Upvote"
                >
                    <UpIcon />
                </PillButton>
                <PillDivider />
                <PillCount $up={upActive} $down={downActive}>
                    {displayVotes}
                </PillCount>
                <PillDivider />
                <PillButton
                    $active={downActive}
                    $bouncing={bounce === -1}
                    disabled={hasPendingVote} title={voteStatus || undefined} aria-busy={hasPendingVote}
                    onClick={onClick(-1)}
                    aria-label="Downvote"
                >
                    <DownIcon />
                </PillButton>
            </PillRoot>
        );
    }

    // Column mode (comments)
    const isComment = Number(post.level) > 0;
    const hasExplicit = !!(state.posts && state.posts[post.post_id] && Object.prototype.hasOwnProperty.call(state.posts[post.post_id], 'collapsed'));
    const isCollapsed = hasExplicit ? !!state.posts[post.post_id].collapsed : !!post.collapsed;
    const onToggleCollapsed = () => updatePost(post.post_id, { collapsed: !isCollapsed });

    return (
        <VoteColumn>
            {isComment && showToggle && (
                <CollapseToggle onClick={onToggleCollapsed} aria-label={isCollapsed ? 'Expand' : 'Collapse'}>
                    [{isCollapsed ? '+' : '−'}]
                </CollapseToggle>
            )}
            {(!isComment || !isCollapsed) && (
                <ColumnButton
                    $up
                    $active={upActive}
                    disabled={hasPendingVote} title={voteStatus || undefined} aria-busy={hasPendingVote}
                    onClick={onClick(+1)}
                    aria-label="Upvote"
                >
                    <UpIcon />
                </ColumnButton>
            )}
            {!isComment && <ColumnCount>{displayVotes}</ColumnCount>}
            {(!isComment || !isCollapsed) && (
                <ColumnButton
                    $active={downActive}
                    disabled={hasPendingVote} title={voteStatus || undefined} aria-busy={hasPendingVote}
                    onClick={onClick(-1)}
                    aria-label="Downvote"
                >
                    <DownIcon />
                </ColumnButton>
            )}
        </VoteColumn>
    );
}

export default DefaultVoteSection;
