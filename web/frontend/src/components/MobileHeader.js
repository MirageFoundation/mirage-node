import React, { useState, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import styled from 'styled-components';

const MobileHeaderContainer = styled.div`
    display: none;
    
    @media (max-width: 600px) {
        display: flex;
        flex-direction: column;
        padding: 0.6rem 0 0.5rem 0;
    }
`;

const MobileHeaderRow = styled.div`
    display: flex;
    flex-direction: row;
    align-items: center;
    justify-content: space-between;
    gap: 0.75rem;
    width: 100%;
    position: relative;
`;

const MobileBrandText = styled.div`
    font-size: 1.6rem;
    font-weight: 800;
    letter-spacing: 0.05rem;
    color: ${({ theme }) => theme?.colors?.text || '#FFFFFF'};
    text-transform: uppercase;
    flex-shrink: 0;
    line-height: 1;
    cursor: pointer;
    transform: ${({ $hidden }) => $hidden ? 'translateX(-100px)' : 'translateX(0)'};
    opacity: ${({ $hidden }) => $hidden ? 0 : 1};
    transition: transform 0.25s cubic-bezier(0.4, 0, 0.2, 1), opacity 0.2s ease;
    ${({ theme }) => theme?.name !== 'light' && `
        animation: glowWander 8s ease-in-out infinite;
    `}

    @keyframes glowWander {
        0% {
            text-shadow: 
                0 0 12px rgba(255, 255, 255, 0.4),
                6px 2px 15px rgba(255, 255, 255, 0.25);
        }
        25% {
            text-shadow: 
                0 0 14px rgba(255, 255, 255, 0.35),
                -4px 4px 12px rgba(255, 255, 255, 0.2);
        }
        50% {
            text-shadow: 
                0 0 10px rgba(255, 255, 255, 0.45),
                -6px -2px 15px rgba(255, 255, 255, 0.25);
        }
        75% {
            text-shadow: 
                0 0 13px rgba(255, 255, 255, 0.38),
                4px -4px 12px rgba(255, 255, 255, 0.2);
        }
        100% {
            text-shadow: 
                0 0 12px rgba(255, 255, 255, 0.4),
                6px 2px 15px rgba(255, 255, 255, 0.25);
        }
    }
`;

const MobileSearchWrapper = styled.div`
    display: flex;
    align-items: center;
    justify-content: flex-end;
    position: relative;
    height: 1.6rem;
    width: 1.6rem;
`;

const MobileSearchButton = styled.button`
    width: 1.6rem;
    height: 1.6rem;
    border-radius: 50%;
    border: 1px solid ${({ theme }) => theme?.colors?.border || '#444'};
    background: ${({ theme }) => theme?.colors?.panelAlt || '#33373C'};
    color: ${({ theme }) => theme?.colors?.text || '#FFFFFF'};
    display: flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    transition: opacity 0.15s ease, background 0.2s ease, border-color 0.2s ease;
    flex-shrink: 0;
    opacity: ${({ $hidden }) => $hidden ? 0 : 1};
    pointer-events: ${({ $hidden }) => $hidden ? 'none' : 'auto'};
    padding: 0;
    
    &:hover {
        background: ${({ theme }) => theme?.colors?.accent || '#3A3F46'};
        border-color: ${({ theme }) => theme?.colors?.link || '#667eea'};
    }
    
    &:active {
        transform: scale(0.95);
    }
    
    svg {
        width: 1rem;
        height: 1rem;
        fill: currentColor;
    }
`;

const MobileSearchInputWrapper = styled.div`
    position: absolute;
    top: 0;
    bottom: 0;
    right: 0;
    display: flex;
    align-items: center;
    background: ${({ theme, $expanded }) => $expanded ? (theme?.colors?.panelAlt || '#33373C') : 'transparent'};
    border: ${({ $expanded, theme }) => $expanded ? `1px solid ${theme?.colors?.border || '#444'}` : '1px solid transparent'};
    border-radius: 20px;
    overflow: hidden;
    width: ${({ $expanded }) => $expanded ? '100%' : '1.6rem'};
    pointer-events: ${({ $expanded }) => $expanded ? 'auto' : 'none'};
    transition: width 0.25s cubic-bezier(0.4, 0, 0.2, 1), background 0.2s ease, border 0.2s ease;
`;

const MobileSearchInput = styled.input`
    flex: 1;
    min-width: 0;
    padding: 0.4rem 0.6rem;
    padding-right: 2rem;
    background: transparent;
    border: none;
    color: ${({ theme }) => theme?.colors?.text || '#FFFFFF'};
    font-size: 0.75rem;
    font-family: inherit;
    opacity: ${({ $visible }) => $visible ? 1 : 0};
    transition: opacity 0.15s ease 0.1s;
    
    &::placeholder {
        color: ${({ theme }) => theme?.colors?.subtleText || '#888'};
    }
    
    &:focus {
        outline: none;
    }
`;

const MobileSearchClose = styled.button`
    position: absolute;
    right: 8px;
    top: 50%;
    transform: translateY(-50%);
    width: 24px;
    height: 24px;
    border-radius: 50%;
    border: none;
    background: ${({ theme }) => theme?.colors?.border || '#444'};
    color: ${({ theme }) => theme?.colors?.text || '#FFFFFF'};
    display: flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    font-size: 14px;
    line-height: 1;
    opacity: ${({ $visible }) => $visible ? 1 : 0};
    transition: opacity 0.15s ease 0.1s;
    
    &:hover {
        background: ${({ theme }) => theme?.colors?.accent || '#555'};
    }
`;

const MobileBrandDivider = styled.div`
    width: 100%;
    height: 1px;
    background: ${({ theme }) => theme?.colors?.border || '#333'};
    margin-top: 0.5rem;
`;

const MobileHeader = () => {
    const navigate = useNavigate();
    const [searchQuery, setSearchQuery] = useState('');
    const [searchExpanded, setSearchExpanded] = useState(false);
    const searchInputRef = useRef(null);

    const handleSearchKeyDown = (e) => {
        if (e.key === 'Enter' && searchQuery.trim()) {
            navigate(`/search?q=${encodeURIComponent(searchQuery.trim())}`);
            setSearchExpanded(false);
            setSearchQuery('');
        } else if (e.key === 'Escape') {
            setSearchExpanded(false);
        }
    };

    const handleSearchOpen = () => {
        setSearchExpanded(true);
        setTimeout(() => {
            searchInputRef.current?.focus();
        }, 50);
    };

    const handleSearchClose = () => {
        setSearchExpanded(false);
        setSearchQuery('');
    };

    return (
        <MobileHeaderContainer>
            <MobileHeaderRow>
                <MobileBrandText $hidden={searchExpanded} onClick={() => { window.location.href = '/home'; }}>MIRAGE</MobileBrandText>
                <MobileSearchWrapper>
                    <MobileSearchButton
                        onClick={handleSearchOpen}
                        aria-label="Search"
                        $hidden={searchExpanded}
                    >
                        <svg viewBox="0 0 24 24">
                            <path d="M15.5 14h-.79l-.28-.27C15.41 12.59 16 11.11 16 9.5 16 5.91 13.09 3 9.5 3S3 5.91 3 9.5 5.91 16 9.5 16c1.61 0 3.09-.59 4.23-1.57l.27.28v.79l5 4.99L20.49 19l-4.99-5zm-6 0C7.01 14 5 11.99 5 9.5S7.01 5 9.5 5 14 7.01 14 9.5 11.99 14 9.5 14z" />
                        </svg>
                    </MobileSearchButton>
                </MobileSearchWrapper>
                <MobileSearchInputWrapper $expanded={searchExpanded}>
                    <MobileSearchInput
                        ref={searchInputRef}
                        type="text"
                        placeholder="Search topics, users, posts..."
                        value={searchQuery}
                        onChange={(e) => setSearchQuery(e.target.value)}
                        onKeyDown={handleSearchKeyDown}
                        $visible={searchExpanded}
                    />
                    <MobileSearchClose onClick={handleSearchClose} $visible={searchExpanded}>
                        ×
                    </MobileSearchClose>
                </MobileSearchInputWrapper>
            </MobileHeaderRow>
            <MobileBrandDivider />
        </MobileHeaderContainer>
    );
};

export default MobileHeader;

