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
    transition: all 0.15s ease;
    border: none;
    font-family: inherit;
    width: 32px;
    height: 32px;
    border-radius: 6px;
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    color: #FFFFFF;
    box-shadow: 0 2px 8px rgba(102, 126, 234, 0.3);

    &:hover:not(:disabled) {
        box-shadow: 0 4px 12px rgba(102, 126, 234, 0.45);
        transform: translateY(-1px);
    }

    &:active:not(:disabled) {
        transform: translateY(0);
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
    border-radius: 8px;
    overflow: hidden;
    border: 1px solid ${({ theme }) => theme?.colors?.border || '#444'};
    background-color: ${({ theme }) => theme?.colors?.panelAlt || '#1f2328'};
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
    border: 2px solid ${({ theme }) => theme?.colors?.border || '#444'};
    border-top-color: ${({ theme }) => theme?.colors?.subtleText || '#bcb1a2'};
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


