import React from 'react';
import styled, { keyframes, css } from 'styled-components';

/**
 * default skeleton primitives.
 *
 * Per sub-plan 06.10 and RULES.md:
 *   R1 — Skeleton tile sits on `panelAlt` so it reads as a lifted placeholder
 *        on the single `bg` canvas.
 *   R2 — All colors from tokens (no raw hex).
 *   R5 — Non-interactive; no focus ring / hover state.
 *   R7 — Heights match the real type scale to avoid layout shift on hydration.
 *
 * Exports:
 *   - `Skeleton`        — single rounded placeholder block.
 *   - `SkeletonText`    — stacked lines with a short final line.
 *   - `SkeletonCircle`  — avatar / dot placeholder.
 *   - `SkeletonBlock`   — aspect-ratio media placeholder.
 *   - Composite row loaders: `FeedCardSkeleton`, `CommentSkeleton`,
 *     `ListRowSkeleton`, `InfoPanelSkeleton`, `ProfileHeaderSkeleton`.
 */

const pulse = keyframes`
    0%   { opacity: 0.55; }
    50%  { opacity: 0.85; }
    100% { opacity: 0.55; }
`;

const baseSurface = css`
    background: ${({ theme }) => theme.colors.panelAlt};
    /* R5 — never interactive. */
    pointer-events: none;
    user-select: none;
    /* Slight border helps the tile read on bg when panelAlt is close to bg. */
    border: 1px solid ${({ theme }) => theme.colors.borderSubtle};
    animation: ${pulse} 1.2s ease-in-out infinite;

    @media (prefers-reduced-motion: reduce) {
        animation: none;
    }
`;

const Block = styled.span`
    ${baseSurface};
    display: ${({ $inline }) => ($inline ? 'inline-block' : 'block')};
    width: ${({ $width }) => $width || '100%'};
    height: ${({ $height }) => $height || '1rem'};
    border-radius: ${({ $radius }) => $radius || '4px'};
    vertical-align: middle;
`;

/** Single rectangular placeholder. */
export function Skeleton({ width, height, radius, inline, style, ...rest }) {
    return (
        <Block
            $width={width}
            $height={height}
            $radius={radius}
            $inline={inline}
            style={style}
            aria-hidden="true"
            {...rest}
        />
    );
}

const TextStack = styled.span`
    display: flex;
    flex-direction: column;
    gap: ${({ $gap }) => $gap || '0.45rem'};
    width: 100%;
`;

/** Stacked body text placeholder. Last line shortens to look natural. */
export function SkeletonText({ lines = 3, lineHeight = '0.75rem', gap, lastLineWidth = '60%', style }) {
    const count = Math.max(1, Math.floor(lines));
    return (
        <TextStack $gap={gap} style={style} aria-hidden="true">
            {Array.from({ length: count }).map((_, idx) => (
                <Skeleton
                    key={idx}
                    height={lineHeight}
                    width={idx === count - 1 && count > 1 ? lastLineWidth : '100%'}
                />
            ))}
        </TextStack>
    );
}

const Circle = styled.span`
    ${baseSurface};
    display: inline-block;
    width: ${({ $size }) => `${$size}px`};
    height: ${({ $size }) => `${$size}px`};
    border-radius: 50%;
    flex-shrink: 0;
`;

/** Circle placeholder for avatars / dots. */
export function SkeletonCircle({ size = 32, style }) {
    return <Circle $size={size} style={style} aria-hidden="true" />;
}

const AspectBlock = styled.span`
    ${baseSurface};
    display: block;
    width: 100%;
    aspect-ratio: ${({ $aspect }) => $aspect || '16 / 9'};
    border-radius: ${({ $radius }) => $radius || '10px'};
`;

/** Media / hero placeholder with a fixed aspect ratio. */
export function SkeletonBlock({ aspect, radius, style }) {
    return <AspectBlock $aspect={aspect} $radius={radius} style={style} aria-hidden="true" />;
}

/* --------------------------------------------------------------------- */
/* Composite loaders                                                      */
/* --------------------------------------------------------------------- */

const RowContainer = styled.div`
    display: flex;
    gap: 0.75rem;
    align-items: flex-start;
    padding: 0.75rem 0.75rem;
    border-bottom: 1px solid ${({ theme }) => theme.colors.border};
    box-sizing: border-box;
    width: 100%;
`;

const RowBody = styled.div`
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
    flex: 1;
    min-width: 0;
`;

const MetaRow = styled.div`
    display: flex;
    gap: 0.5rem;
    align-items: center;
`;

/** Feed card skeleton — mirrors the CardView row shape. */
export function FeedCardSkeleton() {
    return (
        <RowContainer role="status" aria-label="Loading post">
            <SkeletonCircle size={36} />
            <RowBody>
                <MetaRow>
                    <Skeleton width="90px" height="0.65rem" />
                    <Skeleton width="60px" height="0.65rem" />
                    <Skeleton width="40px" height="0.65rem" />
                </MetaRow>
                <Skeleton width="85%" height="1rem" radius="4px" />
                <Skeleton width="65%" height="0.8rem" radius="4px" />
                <MetaRow>
                    <Skeleton width="48px" height="0.7rem" />
                    <Skeleton width="56px" height="0.7rem" />
                    <Skeleton width="44px" height="0.7rem" />
                </MetaRow>
            </RowBody>
        </RowContainer>
    );
}

/** Render N feed card skeletons stacked. */
export function FeedCardSkeletonList({ count = 4 }) {
    return (
        <div role="status" aria-label="Loading posts">
            {Array.from({ length: count }).map((_, idx) => (
                <FeedCardSkeleton key={idx} />
            ))}
        </div>
    );
}

const CommentContainer = styled.div`
    display: flex;
    gap: 0.6rem;
    align-items: flex-start;
    padding: 0.6rem 0.75rem;
    border-bottom: 1px solid ${({ theme }) => theme.colors.border};
    box-sizing: border-box;
`;

const CommentBody = styled.div`
    display: flex;
    flex-direction: column;
    gap: 0.4rem;
    flex: 1;
    min-width: 0;
`;

/** Comment thread skeleton. */
export function CommentSkeleton({ indent = 0 }) {
    return (
        <CommentContainer style={indent ? { marginLeft: `${indent * 16}px` } : undefined}>
            <SkeletonCircle size={24} />
            <CommentBody>
                <MetaRow>
                    <Skeleton width="80px" height="0.6rem" />
                    <Skeleton width="40px" height="0.6rem" />
                </MetaRow>
                <SkeletonText lines={2} lineHeight="0.7rem" gap="0.35rem" />
            </CommentBody>
        </CommentContainer>
    );
}

/** Generic list row skeleton (avatar + name + meta). */
export function ListRowSkeleton({ hasAvatar = true, showMeta = true }) {
    return (
        <RowContainer role="status" aria-label="Loading row">
            {hasAvatar && <SkeletonCircle size={28} />}
            <RowBody>
                <Skeleton width="40%" height="0.85rem" />
                {showMeta && <Skeleton width="65%" height="0.65rem" />}
            </RowBody>
        </RowContainer>
    );
}

export function ListRowSkeletonList({ count = 5, hasAvatar = true, showMeta = true }) {
    return (
        <div role="status" aria-label="Loading list">
            {Array.from({ length: count }).map((_, idx) => (
                <ListRowSkeleton key={idx} hasAvatar={hasAvatar} showMeta={showMeta} />
            ))}
        </div>
    );
}

const InfoPanel = styled.div`
    display: flex;
    flex-direction: column;
    gap: 0.6rem;
    padding: 0.75rem 0.75rem;
    border-bottom: 1px solid ${({ theme }) => theme.colors.border};
`;

const InfoRow = styled.div`
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.75rem;
`;

/** Info panel skeleton — label + value rows (Network / Stats / Subscription). */
export function InfoPanelSkeleton({ rows = 4 }) {
    return (
        <InfoPanel role="status" aria-label="Loading info">
            {Array.from({ length: rows }).map((_, idx) => (
                <InfoRow key={idx}>
                    <Skeleton width="35%" height="0.75rem" />
                    <Skeleton width="45%" height="0.75rem" />
                </InfoRow>
            ))}
        </InfoPanel>
    );
}

const ProfileHeader = styled.div`
    display: flex;
    gap: 0.85rem;
    align-items: center;
    padding: 1rem 0.75rem;
    border-bottom: 1px solid ${({ theme }) => theme.colors.border};
`;

const ProfileBody = styled.div`
    display: flex;
    flex-direction: column;
    gap: 0.55rem;
    flex: 1;
    min-width: 0;
`;

/** Profile header skeleton — avatar + name + stat row. */
export function ProfileHeaderSkeleton() {
    return (
        <ProfileHeader role="status" aria-label="Loading profile">
            <SkeletonCircle size={64} />
            <ProfileBody>
                <Skeleton width="45%" height="1.1rem" />
                <Skeleton width="30%" height="0.7rem" />
                <MetaRow>
                    <Skeleton width="52px" height="0.65rem" />
                    <Skeleton width="52px" height="0.65rem" />
                    <Skeleton width="52px" height="0.65rem" />
                </MetaRow>
            </ProfileBody>
        </ProfileHeader>
    );
}

const PageHeaderWrap = styled.div`
    display: flex;
    flex-direction: column;
    gap: 0.45rem;
    padding: 0.85rem 0.75rem 0.75rem;
    border-bottom: 1px solid ${({ theme }) => theme.colors.border};
`;

/**
 * Page-header skeleton — a short title line and optional subtitle line
 * that mirrors the real `HeaderRow` / `HeaderSubRow` rhythm used across
 * the `default` route shells (Follows, Reports, Agents, Discover,
 * Search, Stats, Network, Inbox, ViewPost). Title defaults to ~40%
 * width (≈ a one- or two-word heading), subtitle to ~60%.
 */
export function PageHeaderSkeleton({ showSubtitle = true, titleWidth = '35%', subtitleWidth = '55%' }) {
    return (
        <PageHeaderWrap role="status" aria-label="Loading header">
            <Skeleton width={titleWidth} height="1.05rem" />
            {showSubtitle && <Skeleton width={subtitleWidth} height="0.7rem" />}
        </PageHeaderWrap>
    );
}

export default Skeleton;
