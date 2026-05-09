import React, { useState, useRef, useEffect, useCallback } from 'react';
import ReactDOM from 'react-dom';
import styled from 'styled-components';

// Build-time fallback (used if runtime config not available)
const BUILD_TIME_GIPHY_KEY = (process.env.REACT_APP_GIPHY_API_KEY || '').trim();
const GIPHY_SEARCH_URL = 'https://api.giphy.com/v1/gifs/search';
const GIPHY_TRENDING_URL = 'https://api.giphy.com/v1/gifs/trending';

// Get Giphy API key: runtime config (from backend) takes precedence over build-time env
function getGiphyApiKey() {
    try {
        const raw = localStorage.getItem('nodeConfig');
        if (raw) {
            const config = JSON.parse(raw);
            if (config.giphy_api_key) {
                return config.giphy_api_key.trim();
            }
        }
    } catch (_) { }
    return BUILD_TIME_GIPHY_KEY;
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
    transition: background 0.12s ease, color 0.12s ease;
    font-family: inherit;
    width: 36px;
    height: 28px;
    padding: 0;
    border-radius: 8px;
    background: transparent;
    color: ${({ theme }) => theme.colors.feedCtrlText};
    border: 1px solid transparent;
    box-shadow: none;

    svg {
        width: 28px;
        height: 28px;
        display: block;
    }

    &:hover:not(:disabled) {
        background: ${({ theme }) => theme.colors.feedCtrlHoverBg};
        color: ${({ theme }) => theme.colors.text};
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

const Popover = styled.div`
    position: fixed;
    z-index: 10100;
    background: ${({ theme }) => theme.colors.pickerBg};
    border: 1px solid ${({ theme }) => theme.colors.border};
    border-radius: 12px;
    box-shadow: ${({ theme }) =>
        theme.name === 'dark'
            ? '0 12px 32px rgba(0, 0, 0, 0.55)'
            : '0 12px 32px rgba(0, 0, 0, 0.18)'};
    width: 340px;
    height: 400px;
    display: flex;
    flex-direction: column;
    overflow: hidden;

    @media (max-width: 600px) {
        left: 10px !important;
        right: 10px !important;
        width: auto !important;
        bottom: 60px !important;
        top: auto !important;
        max-height: 55vh;
    }
`;

const SearchHeader = styled.div`
    display: flex;
    align-items: center;
    padding: 0.5rem 0.6rem;
    border-bottom: 1px solid ${({ theme }) => theme.colors.border};
    gap: 0.4rem;
`;

const SearchInput = styled.input`
    flex: 1;
    background: ${({ theme }) => theme.colors.bg};
    border: 1px solid ${({ theme }) => theme.colors.border};
    border-radius: 8px;
    padding: 0.4rem 0.65rem;
    font-size: 0.7rem;
    color: ${({ theme }) => theme.colors.text};
    outline: none;
    transition: border-color 0.12s ease;

    &:hover {
        border-color: ${({ theme }) => theme.colors.borderStrong};
    }
    &:focus {
        border-color: ${({ theme }) => theme.colors.borderStrong};
    }

    &::placeholder {
        color: ${({ theme }) => theme.colors.subtleText};
    }
`;

const GifGrid = styled.div`
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    grid-auto-rows: 100px;
    gap: 6px;
    padding: 0.65rem;
    overflow-y: auto;
    flex: 1;
`;

const GifItem = styled.button`
    width: 100%;
    height: 100px;
    border: 1px solid transparent;
    background: transparent;
    border-radius: 8px;
    cursor: pointer;
    padding: 0;
    transition: background 0.12s ease, border-color 0.12s ease;
    overflow: hidden;

    &:hover {
        border-color: ${({ theme }) => theme.colors.borderSubtle};
        background: ${({ theme }) => theme.colors.feedCtrlHoverBg};
    }

    &:focus {
        outline: none;
    }
    &:focus-visible {
        outline: 2px solid ${({ theme }) => theme.colors.focusBlue};
        outline-offset: 2px;
    }

    img {
        width: 100%;
        height: 100%;
        object-fit: cover;
        display: block;
    }
`;

const CloseButton = styled.button`
    flex-shrink: 0;
    width: 24px;
    height: 24px;
    border-radius: 50%;
    border: 1px solid transparent;
    background: transparent;
    color: ${({ theme }) => theme.colors.subtleText};
    cursor: pointer;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    font-size: 0.9rem;
    font-weight: 400;
    line-height: 1;
    transition: background 0.12s ease, color 0.12s ease;
    padding: 0;

    & > * {
        display: block;
        line-height: 1;
    }

    &:hover {
        background: ${({ theme }) => theme.colors.feedCtrlHoverBg};
        color: ${({ theme }) => theme.colors.text};
    }
`;

const LoadingText = styled.div`
    padding: 2rem;
    text-align: center;
    color: ${({ theme }) => theme.colors.subtleText};
    font-size: 0.7rem;
`;

const PoweredBy = styled.div`
    padding: 0.4rem 0.5rem;
    text-align: center;
    font-size: 0.55rem;
    font-weight: 500;
    color: ${({ theme }) => theme.colors.subtleText};
    border-top: 1px solid ${({ theme }) => theme.colors.border};
    letter-spacing: 0.02em;
`;

const GifIcon = () => (
    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
        <text
            x="12"
            y="16"
            textAnchor="middle"
            fontSize="9"
            fontFamily="-apple-system, system-ui, sans-serif"
            fontWeight="800"
            letterSpacing="0.3"
            fill="currentColor"
        >GIF</text>
    </svg>
);

/* renderTrigger (optional): ({ buttonRef, isOpen, toggle, disabled }) => ReactNode
 *   When provided, replaces the default icon button. The picker still
 *   owns open/close state and popover positioning — the consumer only
 *   supplies the trigger element and must attach `buttonRef` so
 *   positioning math works. */
export default function GifPicker({ onSelect, disabled = false, renderTrigger }) {
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

    const toggle = () => setIsOpen(prev => !prev);
    const triggerDisabled = disabled || !apiKey;

    return (
        <PickerWrapper>
            {renderTrigger ? (
                renderTrigger({ buttonRef, isOpen, toggle, disabled: triggerDisabled })
            ) : (
                <PickerButton
                    ref={buttonRef}
                    type="button"
                    tabIndex={-1}
                    onClick={toggle}
                    disabled={triggerDisabled}
                    aria-label="GIFs"
                    title={apiKey ? 'GIFs' : 'GIFs disabled (missing API key)'}
                >
                    <GifIcon />
                </PickerButton>
            )}

            {isOpen && ReactDOM.createPortal(
                <Popover
                    ref={popoverRef}
                    style={{ top: position.top, left: position.left }}
                >
                    <SearchHeader>
                        <SearchInput
                            ref={searchInputRef}
                            type="text"
                            placeholder="Search GIFs..."
                            value={searchQuery}
                            onChange={handleSearchChange}
                        />
                        <CloseButton onClick={() => setIsOpen(false)} aria-label="Close"><span>×</span></CloseButton>
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
