import styled from 'styled-components';
import { requireThemeColor } from '../../../utils/themeColor';

/**
 * The flat control shared by the feed and community headers — sort, view
 * mode, curation lens, and membership. One definition so those rows cannot
 * drift into different heights, weights and font sizes.
 */
const FeedControlButton = styled.button`
    display: inline-flex;
    align-items: center;
    gap: 0.25rem;
    height: 28px;
    padding: 0 0.4rem;
    background: transparent;
    border: none;
    border-radius: 6px;
    color: ${({ theme }) => requireThemeColor(theme, 'feedCtrlText')};
    font-family: inherit;
    font-size: 0.68rem;
    font-weight: 400;
    cursor: pointer;
    outline: none;
    line-height: 1;

    & > svg {
        color: inherit;
        fill: currentColor;
    }

    &:hover:not(:disabled),
    &[aria-expanded='true'] {
        background: ${({ theme }) => requireThemeColor(theme, 'feedCtrlHoverBg')};
    }

    &:focus-visible {
        outline: 2px solid ${({ theme }) => requireThemeColor(theme, 'focusBlue')};
        outline-offset: 2px;
    }

    &:disabled {
        opacity: 0.55;
        cursor: not-allowed;
    }
`;

export default FeedControlButton;
