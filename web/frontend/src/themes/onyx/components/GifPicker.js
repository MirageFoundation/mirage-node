import React, { useState, useRef, useEffect, useCallback } from 'react';
import ReactDOM from 'react-dom';
import styled from 'styled-components';

const GIPHY_SEARCH_URL = 'https://api.giphy.com/v1/gifs/search';
const GIPHY_TRENDING_URL = 'https://api.giphy.com/v1/gifs/trending';

// Giphy API key comes from first-party nodeConfig (backend); fail closed if missing.
function getGiphyApiKey() {
    try {
        const raw = localStorage.getItem('nodeConfig');
        if (raw) {
            const config = JSON.parse(raw);
            if (config.giphy_api_key) {
                return String(config.giphy_api_key).trim();
            }
        }
    } catch (_) { }
    return '';
}

const PickerWrapper = styled.div`
    position: relative;
    display: inline-block;
`;

const PickerButton = styled.button`
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

const Popover = styled.div`
    position: fixed;
    z-index: 10100;
    background: ${({ theme }) => theme.colors.panel};
    border: 1px solid ${({ theme }) => theme.colors.border};
    border-radius: 6px;
    box-shadow: 0 8px 32px rgba(0, 0, 0, 0.3);
    width: 340px;
    height: 420px;
    display: flex;
    flex-direction: column;
    overflow: hidden;

    @media (max-width: 600px) {
        left: 10px !important;
        right: 10px !important;
        width: auto !important;
        bottom: 60px !important;
        top: auto !important;
        max-height: 50vh;
    }
`;

const SearchHeader = styled.div`
    display: flex;
    align-items: center;
    padding: 0.75rem;
    border-bottom: 1px solid ${({ theme }) => theme.colors.border};
    gap: 0.5rem;
`;

const SearchInput = styled.input`
    flex: 1;
    background: ${({ theme }) => theme.colors.panelAlt};
    border: 1px solid ${({ theme }) => theme.colors.border};
    border-radius: 6px;
    padding: 0.5rem 0.75rem;
    font-size: 0.8rem;
    color: ${({ theme }) => theme.colors.text};
    outline: none;

    &:focus {
        border-color: ${({ theme }) => theme.colors.focusBorder};
    }

    &::placeholder {
        color: ${({ theme }) => theme.colors.subtleText};
    }
`;

const GifGrid = styled.div`
    display: grid;
    grid-template-columns: repeat(2, 150px);
    grid-auto-rows: 100px;
    gap: 8px;
    padding: 0.75rem;
    overflow-y: auto;
    flex: 1;
    justify-content: center;
`;

const GifItem = styled.button`
    width: 150px;
    height: 100px;
    border: none;
    background: ${({ theme }) => theme.colors.panelAlt};
    border-radius: 6px;
    cursor: pointer;
    padding: 0;
    transition: transform 0.15s ease;
    overflow: hidden;
    flex-shrink: 0;

    &:hover {
        border-color: ${({ theme }) => theme.colors.borderStrong};
    }

    img {
        width: 100%;
        height: 100%;
        object-fit: cover;
    }
`;

const CloseButton = styled.button`
    position: absolute;
    top: 0.5rem;
    right: 0.5rem;
    width: 24px;
    height: 24px;
    border-radius: 50%;
    border: none;
    background: ${({ theme }) => theme.colors.danger};
    color: ${({ theme }) => theme.colors.bg};
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 1rem;
    line-height: 1;
    transition: opacity 0.15s ease;
    z-index: 1;

    &:hover {
        filter: brightness(0.85);
    }
`;

const LoadingText = styled.div`
    padding: 2rem;
    text-align: center;
    color: ${({ theme }) => theme.colors.subtleText};
    font-size: 0.8rem;
`;

const PoweredBy = styled.div`
    padding: 0.5rem;
    text-align: center;
    font-size: 0.65rem;
    color: ${({ theme }) => theme.colors.subtleText};
    border-top: 1px solid ${({ theme }) => theme.colors.border};
`;

const GifIcon = () => (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor">
        <rect x="2" y="4" width="20" height="16" rx="3" ry="3" fill="none" stroke="currentColor" strokeWidth="2" />
        <text x="12" y="15" textAnchor="middle" fontSize="8" fontWeight="bold" fill="currentColor">GIF</text>
    </svg>
);

export default function GifPicker({ onSelect, disabled = false }) {
    const [isOpen, setIsOpen] = useState(false);
    const [searchQuery, setSearchQuery] = useState('');
    const [gifs, setGifs] = useState([]);
    const [loading, setLoading] = useState(false);
    const [position, setPosition] = useState({ top: 0, left: 0 });
    const [apiKey, setApiKey] = useState(getGiphyApiKey);
    const buttonRef = useRef(null);
    const popoverRef = useRef(null);
    const searchInputRef = useRef(null);
    const searchTimeoutRef = useRef(null);

    // Re-check API key when nodeConfig changes (e.g., after login)
    useEffect(() => {
        const handleNodeConfigUpdate = () => {
            setApiKey(getGiphyApiKey());
        };
        window.addEventListener('nodeConfigUpdated', handleNodeConfigUpdate);
        // Also check on mount in case config was already loaded
        setApiKey(getGiphyApiKey());
        return () => window.removeEventListener('nodeConfigUpdated', handleNodeConfigUpdate);
    }, []);

    const updatePosition = useCallback(() => {
        if (!buttonRef.current) return;
        const rect = buttonRef.current.getBoundingClientRect();
        const popoverHeight = 420;
        const popoverWidth = 340;

        let top = rect.top - popoverHeight - 8;
        let left = rect.left;

        if (top < 10) {
            top = rect.bottom + 8;
        }

        if (left + popoverWidth > window.innerWidth - 10) {
            left = window.innerWidth - popoverWidth - 10;
        }
        if (left < 10) {
            left = 10;
        }

        setPosition({ top, left });
    }, []);

    const fetchGifs = useCallback(async (query) => {
        if (!apiKey) {
            setGifs([]);
            return;
        }
        setLoading(true);
        try {
            const url = query
                ? `${GIPHY_SEARCH_URL}?api_key=${apiKey}&q=${encodeURIComponent(query)}&limit=20&rating=pg-13`
                : `${GIPHY_TRENDING_URL}?api_key=${apiKey}&limit=20&rating=pg-13`;

            const response = await fetch(url);
            const data = await response.json();
            setGifs(data.data || []);
        } catch (error) {
            console.error('Failed to fetch GIFs:', error);
            setGifs([]);
        } finally {
            setLoading(false);
        }
    }, [apiKey]);

    useEffect(() => {
        if (isOpen) {
            updatePosition();
            window.addEventListener('resize', updatePosition);
            window.addEventListener('scroll', updatePosition, true);
            return () => {
                window.removeEventListener('resize', updatePosition);
                window.removeEventListener('scroll', updatePosition, true);
            };
        }
    }, [isOpen, updatePosition]);

    useEffect(() => {
        if (isOpen && gifs.length === 0) {
            fetchGifs('');
        }
    }, [isOpen, gifs.length, fetchGifs]);

    useEffect(() => {
        if (isOpen && searchInputRef.current) {
            setTimeout(() => searchInputRef.current?.focus(), 50);
        }
    }, [isOpen]);

    useEffect(() => {
        const handleClickOutside = (event) => {
            if (
                buttonRef.current && !buttonRef.current.contains(event.target) &&
                popoverRef.current && !popoverRef.current.contains(event.target)
            ) {
                setIsOpen(false);
            }
        };

        if (isOpen) {
            document.addEventListener('mousedown', handleClickOutside);
            return () => document.removeEventListener('mousedown', handleClickOutside);
        }
    }, [isOpen]);

    useEffect(() => {
        const handleEscape = (event) => {
            if (event.key === 'Escape') {
                setIsOpen(false);
            }
        };

        if (isOpen) {
            document.addEventListener('keydown', handleEscape);
            return () => document.removeEventListener('keydown', handleEscape);
        }
    }, [isOpen]);

    const handleSearchChange = (e) => {
        const query = e.target.value;
        setSearchQuery(query);

        if (searchTimeoutRef.current) {
            clearTimeout(searchTimeoutRef.current);
        }

        searchTimeoutRef.current = setTimeout(() => {
            fetchGifs(query);
        }, 300);
    };

    const handleGifClick = (gif) => {
        const url = gif.images?.fixed_height?.url || gif.images?.original?.url;
        if (url) {
            onSelect(url);
            setIsOpen(false);
        }
    };

    return (
        <PickerWrapper>
            <PickerButton
                ref={buttonRef}
                type="button"
                tabIndex={-1}
                onClick={() => setIsOpen(!isOpen)}
                disabled={disabled || !apiKey}
                aria-label="GIFs"
                title={apiKey ? 'GIFs' : 'GIFs disabled (missing API key)'}
            >
                <GifIcon />
            </PickerButton>

            {isOpen && ReactDOM.createPortal(
                <Popover
                    ref={popoverRef}
                    style={{ top: position.top, left: position.left }}
                >
                    <CloseButton onClick={() => setIsOpen(false)} aria-label="Close">
                        ×
                    </CloseButton>
                    <SearchHeader>
                        <SearchInput
                            ref={searchInputRef}
                            type="text"
                            placeholder="Search GIFs..."
                            value={searchQuery}
                            onChange={handleSearchChange}
                        />
                    </SearchHeader>
                    <GifGrid>
                        {loading ? (
                            <LoadingText style={{ gridColumn: '1 / -1' }}>Loading...</LoadingText>
                        ) : gifs.length === 0 ? (
                            <LoadingText style={{ gridColumn: '1 / -1' }}>No GIFs found</LoadingText>
                        ) : (
                            gifs.map((gif) => (
                                <GifItem
                                    key={gif.id}
                                    onClick={() => handleGifClick(gif)}
                                    aria-label={gif.title || 'GIF'}
                                >
                                    <img
                                        src={gif.images?.fixed_height_small?.url || gif.images?.preview_gif?.url}
                                        alt={gif.title || ''}
                                        loading="lazy"
                                    />
                                </GifItem>
                            ))
                        )}
                    </GifGrid>
                    <PoweredBy>Powered by GIPHY</PoweredBy>
                </Popover>,
                document.body
            )}
        </PickerWrapper>
    );
}
