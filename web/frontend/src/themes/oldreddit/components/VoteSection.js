import React from "react";
import styled from "styled-components";
import { useVoteHandler, resolveDirection, computeDisplayVotes } from '../../../logic/useVote';

const VoteColumn = styled.div`
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 0;
    align-self: flex-start;
`;

const VoteButton = styled.button`
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
    width: 34px;
    height: 28px;

    &:hover {
        color: ${({ $up, theme }) => $up ? theme.colors.voteUp : theme.colors.voteDown};
    }

    svg {
        display: block;
        width: 25px;
        height: 25px;
        fill: currentColor;
    }

    @media (max-width: 600px) {
        width: 24px;
        height: 20px;

        svg {
            width: 18px;
            height: 18px;
        }
    }
`;

const VoteCount = styled.div`
    font-size: 0.7rem;
    font-weight: 700;
    color: ${({ theme }) => theme.colors.text};
    line-height: 1;
    text-align: center;
    margin: -0.12rem 0;
    padding: 0;

    @media (max-width: 600px) {
        font-size: 0.6rem;
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

function OldRedditVoteSection({ state, post, updatePost, showToggle = true, inline = false }) {
    const { handleVote, isPending, isLocallyPending } = useVoteHandler({ state, updatePost });

    const direction = resolveDirection(post, state);
    const displayVotes = computeDisplayVotes(post, direction);
    const hasPendingVote = isPending(post.post_id) || isLocallyPending(post.post_id);
    const upActive = direction === +1;
    const downActive = direction === -1;

    if (inline) {
        return (
            <InlineVoteArea>
                <VoteButton $up $active={upActive} disabled={hasPendingVote} onClick={() => handleVote(post, +1)}>
                    <UpIcon />
                </VoteButton>
                <InlineVoteCount>{displayVotes}</InlineVoteCount>
                <VoteButton $active={downActive} disabled={hasPendingVote} onClick={() => handleVote(post, -1)}>
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
        <VoteColumn>
            {isComment && showToggle && (
                <CollapseToggle onClick={onToggleCollapsed} aria-label={isCollapsed ? 'Expand' : 'Collapse'}>
                    [{isCollapsed ? '+' : '−'}]
                </CollapseToggle>
            )}
            {!isComment && (
                <VoteButton $up $active={upActive} disabled={hasPendingVote} onClick={() => handleVote(post, +1)}>
                    <UpIcon />
                </VoteButton>
            )}
            {isComment && !isCollapsed && (
                <VoteButton $up $active={upActive} disabled={hasPendingVote} onClick={() => handleVote(post, +1)}>
                    <UpIcon />
                </VoteButton>
            )}
            {!isComment && <VoteCount>{displayVotes}</VoteCount>}
            {!isComment && (
                <VoteButton $active={downActive} disabled={hasPendingVote} onClick={() => handleVote(post, -1)}>
                    <DownIcon />
                </VoteButton>
            )}
            {isComment && !isCollapsed && (
                <VoteButton $active={downActive} disabled={hasPendingVote} onClick={() => handleVote(post, -1)}>
                    <DownIcon />
                </VoteButton>
            )}
        </VoteColumn>
    );
}

export default OldRedditVoteSection;
