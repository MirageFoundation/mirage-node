import { useCallback } from 'react';
import styled from 'styled-components';

const Button = styled.button`
    appearance: none;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    box-sizing: border-box;
    height: var(--community-header-control-height, 28px);
    padding: 0 0.75rem;
    border: 1px solid ${({ $joined, theme }) => ($joined
        ? theme.colors.followBtnBorder
        : theme.colors.followBtnBg)};
    border-radius: 9999px;
    background: ${({ $joined, theme }) => ($joined
        ? 'transparent'
        : theme.colors.followBtnBg)};
    color: ${({ $joined, theme }) => ($joined ? theme.colors.text : '#FFFFFF')};
    font-family: inherit;
    font-size: var(--community-header-control-font-size, 0.68rem);
    font-weight: 600;
    line-height: 1;
    cursor: pointer;
    transition: background 0.12s ease, border-color 0.12s ease, color 0.12s ease;

    &:hover:not(:disabled) {
        background: ${({ $joined, theme }) => ($joined
        ? theme.colors.buttonDangerBg
        : theme.colors.followBtnBgHover)};
        border-color: ${({ $joined, theme }) => ($joined
        ? theme.colors.buttonDangerBorder
        : theme.colors.followBtnBgHover)};
        color: ${({ $joined, theme }) => ($joined ? theme.colors.voteDown : '#FFFFFF')};
    }

    &:focus-visible {
        outline: 2px solid ${({ theme }) => theme.colors.focusBlue};
        outline-offset: 2px;
    }

    &:disabled {
        opacity: 0.55;
        cursor: not-allowed;
    }
`;

const MembershipLabel = styled.span`
    display: inline-grid;

    > span {
        grid-area: 1 / 1;
        white-space: nowrap;
    }

    > span:last-child {
        visibility: hidden;
    }

    ${Button}:hover:not(:disabled) & > span:first-child {
        visibility: hidden;
    }

    ${Button}:hover:not(:disabled) & > span:last-child {
        visibility: visible;
    }
`;

export default function CommunityMembershipButton({
    joined,
    pending = false,
    statusLabel = null,
    communityLabel = '',
    onToggle,
}) {
    const handleClick = useCallback(async () => {
        if (pending || typeof onToggle !== 'function') return;
        console.debug('[community] membership button action', { joined: Boolean(joined) });
        try {
            await onToggle();
        } catch (err) {
            console.error('[community] membership button action failed', {
                error: String(err?.message || err),
            });
        }
    }, [joined, onToggle, pending]);

    const suffix = communityLabel ? ` ${communityLabel}` : '';

    return (
        <Button
            type="button"
            $joined={joined}
            aria-label={joined ? `Leave${suffix}` : `Join${suffix}`}
            disabled={pending}
            onClick={handleClick}
        >
            {pending ? (statusLabel || (joined ? 'Leaving…' : 'Joining…')) : joined ? (
                <MembershipLabel>
                    <span>Joined{suffix}</span>
                    <span>Leave{suffix}</span>
                </MembershipLabel>
            ) : (
                <span>Join{suffix}</span>
            )}
        </Button>
    );
}
