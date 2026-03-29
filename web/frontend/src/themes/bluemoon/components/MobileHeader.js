import React, { useState, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import styled from 'styled-components';
import Storage from '../../../utils/Storage';
import { formatMirageBalance } from '../../../utils/formatters';
import useBalance from '../../../logic/useBalance';

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

const MobileBrandText = styled.a`
    text-decoration: none;
    font-size: 1.6rem;
    font-weight: 800;
    letter-spacing: 0.05rem;
    color: ${({ theme }) => theme.colors.text};
    text-transform: uppercase;
    flex-shrink: 0;
    line-height: 1;
    cursor: pointer;
    transform: ${({ $hidden }) => $hidden ? 'translateX(-100px)' : 'translateX(0)'};
    opacity: ${({ $hidden }) => $hidden ? 0 : 1};
    transition: transform 0.25s cubic-bezier(0.4, 0, 0.2, 1), opacity 0.2s ease;
    ${({ theme }) => theme.name !== 'light' && `
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

const MobileRightSection = styled.div`
    display: flex;
    align-items: center;
    gap: 0.5rem;
    margin-left: auto;
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
    border: 1px solid ${({ theme }) => theme.colors.border};
    background: ${({ theme }) => theme.colors.panelAlt};
    color: ${({ theme }) => theme.colors.text};
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
        background: ${({ theme }) => theme.colors.accent};
        border-color: ${({ theme }) => theme.colors.link};
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
    background: ${({ theme, $expanded }) => $expanded ? (theme.colors.panelAlt) : 'transparent'};
    border: ${({ $expanded, theme }) => $expanded ? `1px solid ${theme.colors.border}` : '1px solid transparent'};
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
    color: ${({ theme }) => theme.colors.text};
    font-size: 0.75rem;
    font-family: inherit;
    opacity: ${({ $visible }) => $visible ? 1 : 0};
    transition: opacity 0.15s ease 0.1s;
    
    &::placeholder {
        color: ${({ theme }) => theme.colors.subtleText};
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
    background: ${({ theme }) => theme.colors.border};
    color: ${({ theme }) => theme.colors.text};
    display: flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    font-size: 14px;
    line-height: 1;
    opacity: ${({ $visible }) => $visible ? 1 : 0};
    transition: opacity 0.15s ease 0.1s;
    
    &:hover {
        background: ${({ theme }) => theme.colors.accent};
    }
`;

const MobileBrandDivider = styled.div`
    width: 100%;
    height: 1px;
    background: ${({ theme }) => theme.colors.border};
    margin-top: 0.5rem;
`;

const MobileBalanceDisplay = styled.div`
    display: flex;
    align-items: center;
    gap: 0.25rem;
    padding: 0.3rem 0.55rem;
    background: ${({ theme }) => theme.colors.panel};
    border: 1px solid ${({ theme }) => theme.colors.border};
    border-radius: 14px;
    flex-shrink: 0;
    transform: ${({ $hidden }) => $hidden ? 'scale(0.8)' : 'scale(1)'};
    opacity: ${({ $hidden }) => $hidden ? 0 : 1};
    transition: transform 0.2s ease, opacity 0.15s ease;
`;

const MobileBalanceAmount = styled.span`
    font-size: 0.7rem;
    font-weight: 600;
    color: ${({ theme }) => theme.colors.text};
    font-variant-numeric: tabular-nums;
`;

const MobileBalanceLabel = styled.span`
    font-size: 0.6rem;
    font-weight: 500;
    color: ${({ theme }) => theme.colors.subtleText};
`;

const MobileHeader = () => {
    const navigate = useNavigate();
    const [searchQuery, setSearchQuery] = useState('');
    const [searchExpanded, setSearchExpanded] = useState(false);
    const searchInputRef = useRef(null);

    const publicKey = Storage.load('publicKey', '');
    const hasPublicKey = !!publicKey;

    const { displayBalance } = useBalance();

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
                <MobileBrandText $hidden={searchExpanded} href="/home">MIRAGE</MobileBrandText>
                <MobileRightSection>
                    {hasPublicKey && (
                        <MobileBalanceDisplay $hidden={searchExpanded} title="Your MIRAGE balance">
                            <MobileBalanceAmount>{displayBalance === null ? '~' : formatMirageBalance(displayBalance)}</MobileBalanceAmount>
                            <MobileBalanceLabel>MIRAGE</MobileBalanceLabel>
                        </MobileBalanceDisplay>
                    )}
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
                </MobileRightSection>
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

