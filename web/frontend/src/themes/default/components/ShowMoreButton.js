import React from 'react';
import styled from 'styled-components';

/**
 * `ShowMoreButton` — shared "Show more" pill used for all pagination /
 * expand triggers in the default theme. Visual parity with
 * `ProfileView::AlgoExpandPill` (algo tab expand control), per sub-plan
 * 06.10 polish round:
 *
 *   R1 — transparent bg on the single canvas; hover lifts to `hoverBg`.
 *   R2 — only token colors (`border`, `borderStrong`, `subtleText`,
 *        `text`, `hoverBg`). No raw hex.
 *   R5 — focus ring on `borderStrong` (no blue default).
 *   R7 — 0.65rem / 600, 26px pill height.
 *
 * Centered inside its own `ShowMoreRow` so callers just drop
 * `<ShowMoreButton onClick={loadMore} loading={isLoadingMore} />` with
 * no extra wrapping markup.
 */

const Row = styled.div`
    display: flex;
    justify-content: center;
    padding: ${({ $spacing }) => ($spacing === 'loose' ? '1.1rem' : '0.45rem')} 1rem;
`;

const Pill = styled.button`
    appearance: none;
    display: inline-flex;
    align-items: center;
    gap: 0.3rem;
    height: 26px;
    padding: 0 14px;
    border-radius: 9999px;
    border: 1px solid ${({ theme }) => theme.colors.border};
    background: transparent;
    color: ${({ theme }) => theme.colors.subtleText};
    font-family: inherit;
    font-size: 0.65rem;
    font-weight: 600;
    cursor: pointer;
    transition: background 0.12s ease, border-color 0.12s ease, color 0.12s ease;

    &:hover:not(:disabled) {
        background: ${({ theme }) => theme.colors.hoverBg};
        border-color: ${({ theme }) => theme.colors.borderStrong};
        color: ${({ theme }) => theme.colors.text};
    }

    &:disabled {
        cursor: not-allowed;
        opacity: 0.55;
    }

    &:focus { outline: none; }
    &:focus-visible { box-shadow: 0 0 0 2px ${({ theme }) => theme.colors.borderStrong}; }
`;

export default function ShowMoreButton({
    onClick,
    loading = false,
    disabled = false,
    loadingLabel = 'Loading…',
    children = 'Show more',
    spacing = 'default',
    ...rest
}) {
    return (
        <Row $spacing={spacing}>
            <Pill
                type="button"
                onClick={onClick}
                disabled={disabled || loading}
                aria-busy={loading ? 'true' : undefined}
                {...rest}
            >
                {loading ? loadingLabel : children}
            </Pill>
        </Row>
    );
}

export { Row as ShowMoreRow, Pill as ShowMorePill };
