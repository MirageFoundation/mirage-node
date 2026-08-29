import { useCallback, useEffect, useRef, useState } from 'react';
import styled from 'styled-components';
import { HiChevronDown } from 'react-icons/hi2';
import { requireThemeColor } from '../../../utils/themeColor';
import FeedControlButton from './FeedControlButton';

const Root = styled.div`
    position: relative;
    display: inline-flex;
    align-items: center;
`;

const Trigger = styled(FeedControlButton)`
    box-sizing: border-box;
    height: var(--community-header-control-height, 28px);
    font-size: var(--community-header-control-font-size, 0.68rem);
`;

const ChevronWrap = styled.span`
    display: inline-flex;
    align-items: center;
    justify-content: center;
    color: inherit;
    transition: transform 0.15s ease;
    transform: ${({ $expanded }) => ($expanded ? 'rotate(180deg)' : 'rotate(0deg)')};

    svg {
        width: 12px;
        height: 12px;
        display: block;
    }
`;

const Menu = styled.div`
    position: absolute;
    top: calc(100% + 6px);
    right: 0;
    min-width: max-content;
    width: max-content;
    padding: 0;
    background: ${({ theme }) => requireThemeColor(theme, 'menuBg')};
    border: 1px solid ${({ theme }) => requireThemeColor(theme, 'border')};
    border-radius: 10px;
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.35);
    z-index: 40;
    display: flex;
    flex-direction: column;
    overflow: hidden;
`;

const MenuItem = styled.button`
    display: flex;
    align-items: center;
    width: 100%;
    padding: 10px 14px;
    white-space: nowrap;
    background: transparent;
    border: none;
    border-radius: 0;
    color: ${({ theme }) => requireThemeColor(theme, 'sidebarItemText')};
    font-family: inherit;
    font-size: 0.7rem;
    font-weight: 400;
    text-align: left;
    cursor: pointer;
    line-height: 1;

    &:hover {
        background: ${({ theme }) => requireThemeColor(theme, 'menuItemHoverBg')};
        color: ${({ theme }) => requireThemeColor(theme, 'menuItemHoverText')};
    }
`;

/**
 * Community membership control — same flat chevron dropdown as Best / view.
 * Trigger shows Join or Joined; the menu exposes the single toggle action.
 */
export default function CommunityMembershipPicker({
    joined,
    pending = false,
    statusLabel = null,
    onToggle,
}) {
    const [open, setOpen] = useState(false);
    const rootRef = useRef(null);

    useEffect(() => {
        if (!open) return undefined;
        const closeOutside = (event) => {
            if (!rootRef.current?.contains(event.target)) setOpen(false);
        };
        document.addEventListener('pointerdown', closeOutside);
        return () => document.removeEventListener('pointerdown', closeOutside);
    }, [open]);

    const handleAction = useCallback(async () => {
        setOpen(false);
        if (pending || typeof onToggle !== 'function') return;
        console.debug('[community] membership menu action', { joined: Boolean(joined) });
        try {
            await onToggle();
        } catch (err) {
            console.error('[community] membership menu action failed', {
                error: String(err?.message || err),
            });
        }
    }, [joined, onToggle, pending]);

    const triggerLabel = pending
        ? (statusLabel || (joined ? 'Leaving...' : 'Joining...'))
        : (joined ? 'Joined' : 'Join');
    const actionLabel = joined ? 'Leave' : 'Join';

    return (
        <Root ref={rootRef}>
            <Trigger
                type="button"
                aria-haspopup="menu"
                aria-expanded={open}
                aria-label="Community membership"
                disabled={pending}
                onClick={() => setOpen((value) => !value)}
            >
                <span>{triggerLabel}</span>
                <ChevronWrap $expanded={open}>
                    <HiChevronDown />
                </ChevronWrap>
            </Trigger>
            {open && (
                <Menu role="menu" aria-label="Community membership">
                    <MenuItem
                        type="button"
                        role="menuitem"
                        onClick={handleAction}
                    >
                        {actionLabel}
                    </MenuItem>
                </Menu>
            )}
        </Root>
    );
}
