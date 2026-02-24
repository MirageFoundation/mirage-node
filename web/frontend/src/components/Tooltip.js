import styled, { css } from 'styled-components';

/**
 * Tooltip behavior:
 * - Default: tooltip shown ABOVE the trigger, left-aligned with first letter
 * - Falls back to below if near top of viewport
 * - No cursor change, no underline
 */

// Default position: above the element, left-aligned
const getPositionStyles = () => css`
    bottom: 100%;
    left: 0;
    margin-bottom: 0.3rem;
`;

// Mobile: same as desktop (above, left-aligned)
const getMobilePositionStyles = () => css`
    bottom: 100%;
    left: 0;
    margin-bottom: 0.3rem;
`;

/**
 * Shared tooltip styles that can be applied to any element via css`` helper
 * Usage: Apply to a styled component that has data-tooltip attribute
 */
export const tooltipStyles = () => css`
    position: relative;
    -webkit-tap-highlight-color: transparent;

    &:hover,
    &:focus,
    &:active {
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

    &[data-tooltip]:not([data-tooltip=""]):hover::after,
    &[data-tooltip]:not([data-tooltip=""]):focus::after,
    &[data-tooltip]:not([data-tooltip=""]):active::after {
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
 * Usage: <TooltipText data-tooltip="Your tooltip text here">Hover me</TooltipText>
 */
export const TooltipText = styled.span`
    ${() => tooltipStyles()}
`;

/**
 * TooltipLabel - A label with tooltip, commonly used for form labels
 * Same as TooltipText but with label-specific styling (starts with subtle color)
 */
export const TooltipLabel = styled.span`
    ${() => tooltipStyles()}
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
    ${tooltipStyles()}

    &::after {
        width: 250px;
        white-space: normal;
        font-size: 0.525rem;
    }
`;

/**
 * TooltipBelow - Tooltip that appears BELOW the trigger.
 * Use inside overflow:hidden containers where the default above-position gets clipped.
 */
export const TooltipBelow = styled.span`
    ${() => tooltipStyles()}
    &::after {
        bottom: auto;
        top: 100%;
        margin-bottom: 0;
        margin-top: 0.3rem;
    }
    @media (max-width: 1000px) {
        &::after {
            bottom: auto;
            top: 100%;
            margin-bottom: 0;
            margin-top: 0.3rem;
        }
    }
`;

/**
 * DottedTooltip - Tooltip with dotted underline on the trigger text.
 * Used for timestamps and metadata that reveal detail on hover.
 */
export const DottedTooltip = styled.span`
    ${() => tooltipStyles()}
    text-decoration: underline;
    text-decoration-style: dotted;
    white-space: nowrap;
`;

export default TooltipText;
