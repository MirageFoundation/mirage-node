import React, { useState, useEffect, useCallback, useRef } from "react";
import styled from "styled-components"
import * as tx from "../utils/tx.js";
import Storage from '../utils/Storage';
import { updateNotification } from '../utils/notifications';

// Global pending votes hook
function usePendingVotes() {
    const [pendingVotes, setPendingVotes] = useState({});

    useEffect(() => {
        let unsubscribe = null;
        let mounted = true;

        const setup = async () => {
            try {
                const initial = await tx.getPendingVotes();
                if (mounted) setPendingVotes(initial);
            } catch (_) { }

            unsubscribe = await tx.addVoteListener((votes) => {
                if (mounted) setPendingVotes(votes);
            });
        };

        setup();

        return () => {
            mounted = false;
            if (unsubscribe) unsubscribe();
        };
    }, []);

    const isPending = useCallback((postId) => {
        const key = String(postId || '').toLowerCase();
        return !!pendingVotes[key];
    }, [pendingVotes]);

    const getDirection = useCallback((postId) => {
        const key = String(postId || '').toLowerCase();
        return pendingVotes[key]?.direction || null;
    }, [pendingVotes]);

    return { pendingVotes, isPending, getDirection };
}

const StyledVoteArea = styled.div`
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    box-sizing: border-box;
    width: ${(props) => (props.compact ? '56px' : '64px')};
    height: ${(props) => (props.compact ? '96px' : '120px')};
    min-height: ${(props) => (props.compact ? '96px' : '120px')};
    padding: ${(props) => (props.compact ? '6px 4px' : '8px 6px')};
    margin-right: 0.25rem;
    border-radius: 14px;
    background: ${({ theme }) => theme?.colors?.panel || '#1f2126'};
    border: 1px solid ${({ theme }) => theme?.colors?.border || 'rgba(0,0,0,0.08)'};
    box-shadow: 0 10px 24px rgba(0,0,0,0.14);
    gap: ${(props) => (props.compact ? '6px' : '10px')};

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
    color: ${({ theme }) => theme?.colors?.text || '#111'};
    font-weight: 700;
    font-size: 0.9rem;
`;

const InlineVoteCount = styled.span`
    text-align: center;
    padding: 0 0.15rem;
    color: ${({ theme }) => theme?.colors?.text || '#111'};
`;

const VoteButton = styled.button`
    appearance: none;
    border: 1px solid transparent;
    background: ${({ active, up, theme }) =>
        active
            ? (up ? 'rgba(22, 163, 74, 0.16)' : 'rgba(220, 38, 38, 0.16)')
            : (theme?.colors?.panelAlt || 'rgba(0,0,0,0.06)')};
    color: ${({ active, up, theme }) =>
        active
            ? (up ? '#16a34a' : '#dc2626')
            : (theme?.colors?.text || '#111')};
    border: 1px solid ${({ theme }) => theme?.colors?.border || 'rgba(0,0,0,0.12)'};
    border-radius: 10px;
    width: ${({ compact }) => (compact ? '28px' : '32px')};
    height: ${({ compact }) => (compact ? '28px' : '32px')};
    display: inline-flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    transition: all 0.15s ease;
    padding: 0;

    &:hover {
        background: ${({ up }) => (up ? 'rgba(22, 163, 74, 0.12)' : 'rgba(220, 38, 38, 0.12)')};
        color: ${({ up }) => (up ? '#16a34a' : '#dc2626')};
        border-color: rgba(0,0,0,0.12);
        transform: translateY(-1px);
    }

    &:active {
        transform: translateY(0);
    }

    svg {
        width: 16px;
        height: 16px;
        fill: currentColor;
    }
`;

const StyledVotes = styled.div`
    text-align: center;
    font-size: 0.95rem;
    font-weight: 700;
    color: ${({ theme }) => theme?.colors?.text || '#FFF'};
`;

const UpIcon = (props) => (
    <svg viewBox="0 0 16 16" width="1em" height="1em" aria-hidden="true" focusable="false" {...props}>
        <path d="M8 3l5 8H3l5-8z" fill="currentColor"></path>
    </svg>
);

const DownIcon = (props) => (
    <svg viewBox="0 0 16 16" width="1em" height="1em" aria-hidden="true" focusable="false" {...props}>
        <path d="M8 13l-5-8h10l-5 8z" fill="currentColor"></path>
    </svg>
);


// collapse toggle is rendered in ViewPostView header for comments
const StyledCollapseToggle = styled.span`
    display: inline-flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    color: ${({ theme }) => theme?.colors?.subtleText || '#CCCCCC'};
    font-size: 0.55rem;
    font-weight: bold;
    padding: 0 0.1rem;
    margin-top: 0;
    line-height: 1em;
    height: 1em;
    user-select: none;
    &:hover { color: ${({ theme }) => theme?.colors?.text || '#EEEEEE'}; }
`

function VoteSection({ state, post, updatePost, showToggle = true, inline = false }) {
    const { isPending } = usePendingVotes();
    const [, forceUpdate] = useState(0);
    const localPendingRef = useRef(new Set());

    const handleVote = async (postObj, direction) => {
        const postIdValue = postObj?.post_id;
        const isLoggedIn = !!state.publicKey;

        if (!isLoggedIn) {
            return;
        }

        if (!postIdValue) {
            return;
        }

        const key = String(postIdValue).toLowerCase();
        if (isPending(postIdValue) || localPendingRef.current.has(key)) {
            return;
        }
        localPendingRef.current.add(key);
        forceUpdate(n => n + 1);

        // Determine current direction: localStorage > state.posts > API response > post.direction
        const ownVotes = Storage.load('votes', {});
        let current;
        if (typeof ownVotes[key] === 'number') {
            current = ownVotes[key];
        } else if (state.posts && state.posts[postIdValue] && typeof state.posts[postIdValue].direction === 'number') {
            current = state.posts[postIdValue].direction;
        } else {
            const apiUserVote = postObj?.user_vote ?? postObj?.my_vote ?? postObj?.userVote ?? postObj?.myVote;
            if (apiUserVote !== undefined && apiUserVote !== null && Number.isFinite(Number(apiUserVote))) {
                current = Number(apiUserVote);
            } else {
                current = (postObj && typeof postObj.direction === 'number') ? postObj.direction : 0;
            }
        }

        // Toggle to 0 if clicking the same direction again
        const newDir = (current === direction) ? 0 : direction;

        // Update state immediately
        if (typeof updatePost === 'function') {
            updatePost(postIdValue, { direction: newDir });
        }

        // Save to localStorage immediately for instant feedback
        try {
            const votes = Storage.load('votes', {}) || {};
            votes[key] = newDir;
            Storage.save('votes', votes);
            forceUpdate(n => n + 1);
        } catch (_) { /* noop */ }

        // Show toast for PoW progress (only for free users)
        const userLevel = Number(Storage.load('user_level', '0') || 0);
        if (userLevel === 0) {
            updateNotification("Solving PoW...", 10);
        }

        // Submit vote to backend
        try {
            const result = await tx.createVote(postIdValue, newDir);
            if (result && result.success === false) {
                throw new Error(result.error || 'Vote failed');
            }
        } catch (e) {
            // Vote failed - revert optimistic update
            try {
                if (typeof updatePost === 'function') {
                    updatePost(postIdValue, { direction: current });
                }
                // Revert localStorage
                const votes = Storage.load('votes', {}) || {};
                if (current === 0) {
                    delete votes[key];
                } else {
                    votes[key] = current;
                }
                Storage.save('votes', votes);
            } catch (_) { /* noop */ }
        } finally {
            localPendingRef.current.delete(key);
            forceUpdate(n => n + 1);
        }
    };

    const displayVoteArea = (post) => {
        const key = String(post.post_id).toLowerCase();
        const hasPendingVote = isPending(post.post_id) || localPendingRef.current.has(key);

        // Direction priority: localStorage > state.posts > API response (user_vote) > post.direction
        // localStorage is checked first for instant optimistic updates when voting
        const ownVotes = Storage.load('votes', {});
        let direction;
        if (typeof ownVotes[key] === 'number') {
            direction = ownVotes[key];
        } else if (state.posts && typeof state.posts[post.post_id]?.direction === 'number') {
            direction = state.posts[post.post_id].direction;
        } else if (hasPendingVote) {
            direction = 0;
        } else {
            const apiUserVote = post?.user_vote ?? post?.my_vote ?? post?.userVote ?? post?.myVote;
            if (apiUserVote !== undefined && apiUserVote !== null && Number.isFinite(Number(apiUserVote))) {
                direction = Number(apiUserVote);
            } else {
                direction = (post && typeof post.direction === 'number') ? post.direction : 0;
            }
        }

        // Display the points adjusted for user's perceived contribution
        // Formula: (actual points) - (user's weight contribution) + (user's perceived +1/-1)
        const rawPoints = typeof post.points === 'number' ? post.points : Number(post.points) || 0;
        const userWeight = typeof post.user_weight === 'number' ? post.user_weight : Number(post.user_weight) || 0;
        const adjustedPoints = rawPoints - userWeight + direction;
        const displayVotes = Math.round(adjustedPoints);

        const isComment = Number(post.level) > 0;
        const hasExplicit = !!(state.posts && state.posts[post.post_id] && Object.prototype.hasOwnProperty.call(state.posts[post.post_id], 'collapsed'));
        const explicitCollapsed = hasExplicit ? !!state.posts[post.post_id].collapsed : null;
        const isCollapsed = hasExplicit ? explicitCollapsed : !!post.collapsed;
        const onToggleCollapsed = () => updatePost(post.post_id, { collapsed: !isCollapsed });

        // Show active state immediately based on direction (no spinner, no waiting)
        const upActive = direction === +1;
        const downActive = direction === -1;

        if (inline) {
            return (
                <InlineVoteArea>
                    <VoteButton
                        compact
                        up
                        active={upActive}
                        disabled={hasPendingVote}
                        onClick={() => handleVote(post, +1)}
                    >
                        <UpIcon />
                    </VoteButton>
                    <InlineVoteCount>{displayVotes}</InlineVoteCount>
                    <VoteButton
                        compact
                        active={downActive}
                        disabled={hasPendingVote}
                        onClick={() => handleVote(post, -1)}
                    >
                        <DownIcon />
                    </VoteButton>
                </InlineVoteArea>
            );
        }

        return (
            <StyledVoteArea compact={isComment}>
                {isComment && showToggle && (
                    <StyledCollapseToggle onClick={onToggleCollapsed} aria-label={isCollapsed ? 'Expand' : 'Collapse'}>
                        [{isCollapsed ? '+' : '−'}]
                    </StyledCollapseToggle>
                )}
                {!isComment && (
                    <VoteButton
                        up
                        active={upActive}
                        disabled={hasPendingVote}
                        onClick={() => handleVote(post, +1)}
                    >
                        <UpIcon />
                    </VoteButton>
                )}
                {isComment && !isCollapsed && (
                    <VoteButton
                        compact
                        up
                        active={upActive}
                        disabled={hasPendingVote}
                        onClick={() => handleVote(post, +1)}
                    >
                        <UpIcon />
                    </VoteButton>
                )}
                {!(post && Number(post.level) > 0) && (
                    <StyledVotes>
                        {displayVotes}
                    </StyledVotes>
                )}
                {!isComment && (
                    <VoteButton
                        active={downActive}
                        disabled={hasPendingVote}
                        onClick={() => handleVote(post, -1)}
                    >
                        <DownIcon />
                    </VoteButton>
                )}
                {isComment && !isCollapsed && (
                    <VoteButton
                        compact
                        active={downActive}
                        disabled={hasPendingVote}
                        onClick={() => handleVote(post, -1)}
                    >
                        <DownIcon />
                    </VoteButton>
                )}
            </StyledVoteArea>
        )
    }

    return (
        <>
            {displayVoteArea(post)}
        </>
    );
}

export default VoteSection;
