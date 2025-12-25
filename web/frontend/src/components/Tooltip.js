import styled, { css } from 'styled-components';

/**
 * Tooltip behavior:
 * - Single unified layout: tooltip is always shown just below the trigger,
 *   aligned to the left and expanding to the right.
 * - Text wraps naturally inside a max‑width box; we don't try to be clever
 *   with different positions.
 */

// We keep this function for API compatibility, but ignore the position
// argument and always use the same \"bottom-right\" layout:
// tooltip appears slightly below and to the right of the trigger.
const getPositionStyles = () => css`
    top: 100%;
    left: 2.5rem;
    margin-top: 0.2rem;
`;

// On mobile, treat \"no space on the right\" as the default and pin to bottom-left.
const getMobilePositionStyles = () => css`
    top: 100%;
    left: 0;
    transform: none;
    margin-top: 0.2rem;
    margin-left: 0;
`;

/**
 * Shared tooltip styles that can be applied to any element via css`` helper
 * Usage: Apply to a styled component that has data-tooltip attribute
 * 
 * @param {string} position - deprecated, ignored (kept only for call‑site compatibility)
 */
export const tooltipStyles = (position = 'right') => css`
    position: relative;
    cursor: help;
    text-decoration: underline dotted;
    text-underline-offset: 2px;
    transition: color 0.2s;
    -webkit-tap-highlight-color: transparent;

    &:hover,
    &:focus,
    &:active {
        color: ${({ theme }) => theme?.colors?.text || '#fff'};
        outline: none;
    }

    &::after {
        content: attr(data-tooltip);
        position: absolute;
        ${getPositionStyles()}
        background: ${({ theme }) => theme?.colors?.panel || '#23272C'};
        border: 1px solid ${({ theme }) => theme?.colors?.border || '#555'};
        color: ${({ theme }) => theme?.colors?.text || '#eee'};
        padding: 0.5rem 0.75rem;
        border-radius: 4px;
        font-size: 0.7rem;
        font-weight: normal;
        white-space: pre-wrap;
        width: max-content;
        max-width: 260px;
        z-index: 1000;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.4);
        line-height: 1.4;
        opacity: 0;
        pointer-events: none;
        transition: opacity 0.15s ease;
        text-align: left;
        text-transform: none;
    }

    &:hover::after,
    &:focus::after,
    &:active::after {
        opacity: 1;
        pointer-events: auto;
    }

    @media (max-width: 1000px) {
        &::after {
            ${getMobilePositionStyles()}
        }
    }
`;

/**
 * TooltipText - A styled span with tooltip functionality
 * Usage: <TooltipText data-tooltip="Your tooltip text here" $position="bottom">Hover me</TooltipText>
 */
export const TooltipText = styled.span`
    ${({ $position }) => tooltipStyles($position || 'right')}
`;

/**
 * TooltipLabel - A label with tooltip, commonly used for form labels
 * Same as TooltipText but with label-specific styling (starts with subtle color)
 */
export const TooltipLabel = styled.span`
    ${({ $position }) => tooltipStyles($position || 'right')}
    color: ${({ theme }) => theme?.colors?.subtleText || '#888'};
`;

/**
 * InfoIcon - A small circular "?" icon with tooltip on hover
 * Usage: <InfoIcon data-tooltip="Explanation text here">?</InfoIcon>
 */
export const InfoIcon = styled.span`
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 0.5rem;
    height: 0.5rem;
    border-radius: 50%;
    background-color: ${({ theme }) => theme?.colors?.accent || '#2E3238'};
    color: ${({ theme }) => theme?.colors?.subtleText || '#ccc'};
    font-size: 0.4rem;
    flex-shrink: 0;
    margin-left: 0.1rem;
    vertical-align: super;
    ${tooltipStyles('top')}
    /* Override: no underline for icon */
    text-decoration: none;

    &::after {
        width: 250px;
        white-space: normal;
        font-size: 0.525rem;
    }
`;

export default TooltipText;

