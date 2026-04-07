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
    transition: transform 0.15s ease, opacity 0.15s ease;
    border: none;
    font-family: inherit;
    width: 32px;
    height: 32px;
    border-radius: 6px;
    background: ${({ theme }) => theme.colors.accent};
    color: ${({ theme }) => theme.colors.text};

    &:hover:not(:disabled) {
        background: ${({ theme }) => theme.colors.accentHover};
    }

    &:disabled {
        opacity: 0.4;
        cursor: not-allowed;
        transform: none !important;
    }

    &:focus {
        outline: none;
    }
`;

export const MediaPreviewWrapper = styled.div`
    position: relative;
    height: 80px;
    max-width: 100%;
    border-radius: 6px;
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
    border-radius: 50%;
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
    border-radius: 50%;
    border: none;
    background-color: ${({ theme }) => theme.colors.danger};
    color: ${({ theme }) => theme.colors.bg};
    font-size: 0.75rem;
    font-weight: 700;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 0;

    &:hover:not(:disabled) {
        filter: brightness(0.85);
    }

    &:disabled {
        opacity: 0.5;
        cursor: not-allowed;
        pointer-events: none;
    }
`;


