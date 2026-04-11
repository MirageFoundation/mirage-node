import styled from "styled-components";

export const MediaRow = styled.div`
    display: flex;
    flex-direction: row;
    align-items: center;
    gap: 0.5rem;
    flex-wrap: wrap;
`;

export const MediaIconButton = styled.button`
    display: inline-flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    transition: background 0.12s ease, color 0.12s ease, border-color 0.12s ease;
    font-family: inherit;
    width: 28px;
    height: 28px;
    border-radius: 8px;
    background: transparent;
    color: ${({ theme }) => theme.colors.feedCtrlText};
    border: 1px solid transparent;
    box-shadow: none;

    svg, img {
        width: 16px;
        height: 16px;
    }

    &:hover:not(:disabled) {
        background: ${({ theme }) => theme.colors.feedCtrlHoverBg};
        color: ${({ theme }) => theme.colors.text};
        box-shadow: none;
    }

    &:active:not(:disabled) {
        transform: none;
    }

    &:disabled {
        opacity: 0.4;
        cursor: not-allowed;
    }

    &:focus {
        outline: none;
    }
    &:focus-visible {
        outline: 2px solid ${({ theme }) => theme.colors.focusBlue};
        outline-offset: 2px;
    }
`;

export const MediaPreviewWrapper = styled.div`
    position: relative;
    height: 80px;
    max-width: 100%;
    border-radius: 8px;
    overflow: hidden;
    border: 1px solid ${({ theme }) => theme.colors.border};
    background-color: ${({ theme }) => theme.colors.panelAlt};
`;

export const MediaPreviewImage = styled.img`
    height: 100%;
    width: auto;
    display: block;
`;

export const MediaSpinner = styled.div`
    position: absolute;
    top: 50%;
    left: 50%;
    width: 26px;
    height: 26px;
    margin-top: -13px;
    margin-left: -13px;
    border-radius: 999px;
    border: 2px solid ${({ theme }) => theme.colors.border};
    border-top-color: ${({ theme }) => theme.colors.subtleText};
    animation: media-spin 0.8s linear infinite;

    @keyframes media-spin {
        0% { transform: rotate(0deg); }
        100% { transform: rotate(360deg); }
    }
`;

export const MediaRemoveButton = styled.button`
    position: absolute;
    top: 4px;
    right: 4px;
    width: 20px;
    height: 20px;
    border-radius: 999px;
    border: none;
    background-color: #dc2626;
    color: #ffffff;
    font-size: 0.75rem;
    font-weight: 700;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    box-shadow: 0 2px 4px rgba(0,0,0,0.4);
    padding: 0;

    &:hover:not(:disabled) {
        background-color: #b91c1c;
    }

    &:disabled {
        opacity: 0.5;
        cursor: not-allowed;
        pointer-events: none;
    }
`;


