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

const PillRoot = styled.div`
    display: inline-flex;
    align-items: center;
    height: 30px;
    padding: 0 2px;
    border-radius: 9999px;
    border: 0.5px solid ${({ theme }) => theme.colors.border};
    background: transparent;
    color: ${({ theme }) => theme.colors.text};
    font-weight: 700;
    font-size: 0.72rem;
    line-height: 1;
`;

const PillDivider = styled.span`
    display: inline-block;
    width: 1px;
    height: 60%;
    background: ${({ theme }) => theme.colors.border};
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
    font-weight: 700;
    height: 100%;
    line-height: 1;
    transition: color 0.12s ease, transform 0.12s ease;

    &:disabled {
        opacity: 0.6;
        cursor: default;
    }

    &:hover:not(:disabled) {
        color: ${({ $up, theme }) => ($up ? theme.colors.voteUp : theme.colors.voteDown)};
    }

    &:active:not(:disabled) {
        transform: scale(0.92);
    }

    svg {
        display: block;
        width: 16px;
        height: 16px;
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
    min-width: 1.2rem;
    padding: 0 8px;
    font: inherit;
    font-weight: 700;
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
        opacity: 0.6;
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

const UpIcon = (props) => (
    <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false" {...props}>
        <path d="M12 4 l8 10 H15 V20 H9 V14 H4 Z" />
    </svg>
);

const DownIcon = (props) => (
    <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false" {...props}>
        <path d="M12 20 l-8 -10 H9 V4 H15 V10 H20 Z" />
    </svg>
);

// ─── Component ─────────────────────────────────────────────────────────────

function MirageAppVoteSection({ state, post, updatePost, showToggle = true, inline = false }) {
    const { handleVote, isPending, isLocallyPending } = useVoteHandler({ state, updatePost });

    const direction = resolveDirection(post, state);
    const displayVotes = computeDisplayVotes(post, direction);
    const hasPendingVote = isPending(post.post_id) || isLocallyPending(post.post_id);
    const upActive = direction === +1;
    const downActive = direction === -1;

    const [bounce, setBounce] = React.useState(null);
    const onClick = (dir) => () => {
        setBounce(dir);
        setTimeout(() => setBounce(null), 320);
        handleVote(post, dir);
    };

    if (inline) {
        return (
            <PillRoot>
                <PillButton
                    $up
                    $active={upActive}
                    $bouncing={bounce === +1}
                    disabled={hasPendingVote}
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
                    disabled={hasPendingVote}
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
                    disabled={hasPendingVote}
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
                    disabled={hasPendingVote}
                    onClick={onClick(-1)}
                    aria-label="Downvote"
                >
                    <DownIcon />
                </ColumnButton>
            )}
        </VoteColumn>
    );
}

export default MirageAppVoteSection;
