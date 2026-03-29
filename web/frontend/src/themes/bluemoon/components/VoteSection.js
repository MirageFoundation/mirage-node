import React from "react";
import styled from "styled-components";
import { useVoteHandler, resolveDirection, computeDisplayVotes } from '../../../logic/useVote';

const StyledVoteArea = styled.div`
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    box-sizing: border-box;
    width: ${({ $compact, theme }) => $compact ? theme.layout.voteAreaWidthCompact : theme.layout.voteAreaWidth};
    height: ${({ $compact, theme }) => $compact ? theme.layout.voteAreaHeightCompact : theme.layout.voteAreaHeight};
    min-height: ${({ $compact, theme }) => {
        const h = $compact ? theme.layout.voteAreaHeightCompact : theme.layout.voteAreaHeight;
        return h === 'auto' ? '0' : h;
    }};
    padding: ${({ $compact, theme }) => $compact ? theme.layout.voteAreaPaddingCompact : theme.layout.voteAreaPadding};
    margin-right: ${({ theme }) => theme.layout.voteAreaMarginRight};
    border-radius: ${({ theme }) => theme.layout.voteAreaRadius};
    background: ${({ theme }) => theme.layout.voteAreaBg};
    border: ${({ theme }) => theme.layout.voteAreaBorder};
    box-shadow: ${({ theme }) => theme.layout.voteAreaShadow};
    gap: ${({ $compact, theme }) => $compact ? theme.layout.voteAreaGapCompact : theme.layout.voteAreaGap};

    @media (max-width: 768px) {
        width: 60px;
        height: 120px;
        min-height: 120px;
        margin-right: 0.65rem;
        padding: 8px 4px;
    }
`;

const InlineVoteArea = styled.div`
    display: inline-flex;
    align-items: center;
    gap: 0.35rem;
    color: ${({ theme }) => theme.colors.text};
    font-weight: 700;
    font-size: 0.9rem;
`;

const InlineVoteCount = styled.span`
    text-align: center;
    padding: 0 0.15rem;
    color: ${({ theme }) => theme.colors.text};
`;

const VoteButton = styled.button`
    appearance: none;
    background: ${({ $active, $up, theme }) =>
        $active
            ? ($up ? 'rgba(22, 163, 74, 0.16)' : 'rgba(220, 38, 38, 0.16)')
            : theme.layout.voteButtonBgInactive};
    color: ${({ $active, $up, theme }) =>
        $active
            ? ($up ? theme.colors.voteUp : theme.colors.voteDown)
            : theme.colors.subtleText};
    border: ${({ theme }) => theme.layout.voteButtonBorder};
    border-radius: ${({ theme }) => theme.layout.voteButtonRadius};
    width: ${({ $compact, theme }) => $compact ? theme.layout.voteButtonSizeCompact : theme.layout.voteButtonSize};
    height: ${({ $compact, theme }) => $compact ? theme.layout.voteButtonSizeCompact : theme.layout.voteButtonSize};
    display: inline-flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    transition: all 0.15s ease;
    padding: 0;

    &:hover {
        background: ${({ $up }) => $up ? 'rgba(22, 163, 74, 0.12)' : 'rgba(220, 38, 38, 0.12)'};
        color: ${({ $up, theme }) => $up ? theme.colors.voteUp : theme.colors.voteDown};
        transform: ${({ theme }) => theme.layout.voteButtonHoverTransform};
    }

    &:active {
        transform: translateY(0);
    }

    svg {
        width: ${({ theme }) => theme.layout.voteIconSize};
        height: ${({ theme }) => theme.layout.voteIconSize};
        fill: currentColor;
    }
`;

const StyledVotes = styled.div`
    text-align: center;
    font-size: ${({ theme }) => theme.layout.voteFontSize};
    font-weight: 700;
    color: ${({ theme }) => theme.colors.text};
    line-height: ${({ theme }) => theme.layout.voteLineHeight};
`;

const StyledCollapseToggle = styled.span`
    display: inline-flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    color: ${({ theme }) => theme.colors.subtleText};
    font-size: 0.55rem;
    font-weight: bold;
    padding: 0 0.1rem;
    margin-top: 0;
    line-height: 1em;
    height: 1em;
    user-select: none;
    &:hover { color: ${({ theme }) => theme.colors.text}; }
`;

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

function BlueMoonVoteSection({ state, post, updatePost, showToggle = true, inline = false }) {
    const { handleVote, isPending, isLocallyPending } = useVoteHandler({ state, updatePost });

    const direction = resolveDirection(post, state);
    const displayVotes = computeDisplayVotes(post, direction);
    const hasPendingVote = isPending(post.post_id) || isLocallyPending(post.post_id);
    const upActive = direction === +1;
    const downActive = direction === -1;

    if (inline) {
        return (
            <InlineVoteArea>
                <VoteButton $compact $up $active={upActive} disabled={hasPendingVote} onClick={() => handleVote(post, +1)}>
                    <UpIcon />
                </VoteButton>
                <InlineVoteCount>{displayVotes}</InlineVoteCount>
                <VoteButton $compact $active={downActive} disabled={hasPendingVote} onClick={() => handleVote(post, -1)}>
                    <DownIcon />
                </VoteButton>
            </InlineVoteArea>
        );
    }

    const isComment = Number(post.level) > 0;
    const hasExplicit = !!(state.posts && state.posts[post.post_id] && Object.prototype.hasOwnProperty.call(state.posts[post.post_id], 'collapsed'));
    const isCollapsed = hasExplicit ? !!state.posts[post.post_id].collapsed : !!post.collapsed;
    const onToggleCollapsed = () => updatePost(post.post_id, { collapsed: !isCollapsed });

    return (
        <StyledVoteArea $compact={isComment}>
            {isComment && showToggle && (
                <StyledCollapseToggle onClick={onToggleCollapsed} aria-label={isCollapsed ? 'Expand' : 'Collapse'}>
                    [{isCollapsed ? '+' : '−'}]
                </StyledCollapseToggle>
            )}
            {!isComment && (
                <VoteButton $up $active={upActive} disabled={hasPendingVote} onClick={() => handleVote(post, +1)}>
                    <UpIcon />
                </VoteButton>
            )}
            {isComment && !isCollapsed && (
                <VoteButton $compact $up $active={upActive} disabled={hasPendingVote} onClick={() => handleVote(post, +1)}>
                    <UpIcon />
                </VoteButton>
            )}
            {!isComment && <StyledVotes>{displayVotes}</StyledVotes>}
            {!isComment && (
                <VoteButton $active={downActive} disabled={hasPendingVote} onClick={() => handleVote(post, -1)}>
                    <DownIcon />
                </VoteButton>
            )}
            {isComment && !isCollapsed && (
                <VoteButton $compact $active={downActive} disabled={hasPendingVote} onClick={() => handleVote(post, -1)}>
                    <DownIcon />
                </VoteButton>
            )}
        </StyledVoteArea>
    );
}

export default BlueMoonVoteSection;
