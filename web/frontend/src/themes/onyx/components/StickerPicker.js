import React, { useState, useRef, useEffect, useCallback } from 'react';
import ReactDOM from 'react-dom';
import styled from 'styled-components';

const STICKER_PACKS = {
    meme_stickers: {
        name: 'Meme Stickers',
        stickers: [
            'https://mirage-img.b-cdn.net/stickers/meme/01.webp',
            'https://mirage-img.b-cdn.net/stickers/meme/02.webp',
            'https://mirage-img.b-cdn.net/stickers/meme/03.webp',
            'https://mirage-img.b-cdn.net/stickers/meme/04.webp',
            'https://mirage-img.b-cdn.net/stickers/meme/05.webp',
            'https://mirage-img.b-cdn.net/stickers/meme/06.webp',
            'https://mirage-img.b-cdn.net/stickers/meme/07.webp',
            'https://mirage-img.b-cdn.net/stickers/meme/08.webp',
            'https://mirage-img.b-cdn.net/stickers/meme/09.webp',
            'https://mirage-img.b-cdn.net/stickers/meme/10.webp',
            'https://mirage-img.b-cdn.net/stickers/meme/11.webp',
            'https://mirage-img.b-cdn.net/stickers/meme/12.webp',
            'https://mirage-img.b-cdn.net/stickers/meme/13.webp',
            'https://mirage-img.b-cdn.net/stickers/meme/14.webp',
            'https://mirage-img.b-cdn.net/stickers/meme/15.webp',
            'https://mirage-img.b-cdn.net/stickers/meme/16.webp',
            'https://mirage-img.b-cdn.net/stickers/meme/17.webp',
            'https://mirage-img.b-cdn.net/stickers/meme/18.webp',
            'https://mirage-img.b-cdn.net/stickers/meme/19.webp',
            'https://mirage-img.b-cdn.net/stickers/meme/20.webp',
            'https://mirage-img.b-cdn.net/stickers/meme/21.webp',
            'https://mirage-img.b-cdn.net/stickers/meme/22.webp',
            'https://mirage-img.b-cdn.net/stickers/meme/23.webp',
            'https://mirage-img.b-cdn.net/stickers/meme/24.webp',
            'https://mirage-img.b-cdn.net/stickers/meme/25.webp',
            'https://mirage-img.b-cdn.net/stickers/meme/26.webp',
            'https://mirage-img.b-cdn.net/stickers/meme/27.webp',
            'https://mirage-img.b-cdn.net/stickers/meme/28.webp',
            'https://mirage-img.b-cdn.net/stickers/meme/29.webp',
            'https://mirage-img.b-cdn.net/stickers/meme/30.webp',
            'https://mirage-img.b-cdn.net/stickers/meme/31.webp',
            'https://mirage-img.b-cdn.net/stickers/meme/32.webp',
            'https://mirage-img.b-cdn.net/stickers/meme/33.webp',
            'https://mirage-img.b-cdn.net/stickers/meme/34.webp',
            'https://mirage-img.b-cdn.net/stickers/meme/35.webp',
            'https://mirage-img.b-cdn.net/stickers/meme/36.webp',
            'https://mirage-img.b-cdn.net/stickers/meme/37.webp',
            'https://mirage-img.b-cdn.net/stickers/meme/38.webp',
            'https://mirage-img.b-cdn.net/stickers/meme/39.webp',
            'https://mirage-img.b-cdn.net/stickers/meme/40.webp',
            'https://mirage-img.b-cdn.net/stickers/meme/41.webp',
            'https://mirage-img.b-cdn.net/stickers/meme/42.webp',
            'https://mirage-img.b-cdn.net/stickers/meme/43.webp',
            'https://mirage-img.b-cdn.net/stickers/meme/44.webp',
            'https://mirage-img.b-cdn.net/stickers/meme/45.webp',
            'https://mirage-img.b-cdn.net/stickers/meme/46.webp',
            'https://mirage-img.b-cdn.net/stickers/meme/47.webp',
            'https://mirage-img.b-cdn.net/stickers/meme/48.webp',
            'https://mirage-img.b-cdn.net/stickers/meme/49.webp',
            'https://mirage-img.b-cdn.net/stickers/meme/50.webp',
            'https://mirage-img.b-cdn.net/stickers/meme/51.webp',
            'https://mirage-img.b-cdn.net/stickers/meme/52.webp',
            'https://mirage-img.b-cdn.net/stickers/meme/53.webp',
            'https://mirage-img.b-cdn.net/stickers/meme/54.webp',
            'https://mirage-img.b-cdn.net/stickers/meme/55.webp',
            'https://mirage-img.b-cdn.net/stickers/meme/56.webp',
            'https://mirage-img.b-cdn.net/stickers/meme/57.webp',
            'https://mirage-img.b-cdn.net/stickers/meme/58.webp',
            'https://mirage-img.b-cdn.net/stickers/meme/59.webp',
            'https://mirage-img.b-cdn.net/stickers/meme/60.webp',
            'https://mirage-img.b-cdn.net/stickers/meme/61.webp',
            'https://mirage-img.b-cdn.net/stickers/meme/62.webp',
            'https://mirage-img.b-cdn.net/stickers/meme/63.webp',
            'https://mirage-img.b-cdn.net/stickers/meme/64.webp',
            'https://mirage-img.b-cdn.net/stickers/meme/65.webp',
            'https://mirage-img.b-cdn.net/stickers/meme/66.webp',
            'https://mirage-img.b-cdn.net/stickers/meme/67.webp',
            'https://mirage-img.b-cdn.net/stickers/meme/68.webp',
            'https://mirage-img.b-cdn.net/stickers/meme/69.webp',
            'https://mirage-img.b-cdn.net/stickers/meme/70.webp',
            'https://mirage-img.b-cdn.net/stickers/meme/71.webp',
            'https://mirage-img.b-cdn.net/stickers/meme/72.webp',
            'https://mirage-img.b-cdn.net/stickers/meme/73.webp',
            'https://mirage-img.b-cdn.net/stickers/meme/74.webp',
            'https://mirage-img.b-cdn.net/stickers/meme/75.webp',
            'https://mirage-img.b-cdn.net/stickers/meme/76.webp',
            'https://mirage-img.b-cdn.net/stickers/meme/77.webp',
            'https://mirage-img.b-cdn.net/stickers/meme/78.webp',
            'https://mirage-img.b-cdn.net/stickers/meme/79.webp',
            'https://mirage-img.b-cdn.net/stickers/meme/80.webp',
            'https://mirage-img.b-cdn.net/stickers/meme/81.webp',
            'https://mirage-img.b-cdn.net/stickers/meme/82.webp',
            'https://mirage-img.b-cdn.net/stickers/meme/83.webp',
            'https://mirage-img.b-cdn.net/stickers/meme/84.webp',
            'https://mirage-img.b-cdn.net/stickers/meme/85.webp',
            'https://mirage-img.b-cdn.net/stickers/meme/86.webp',
            'https://mirage-img.b-cdn.net/stickers/meme/87.webp',
            'https://mirage-img.b-cdn.net/stickers/meme/88.webp',
            'https://mirage-img.b-cdn.net/stickers/meme/89.webp',
            'https://mirage-img.b-cdn.net/stickers/meme/90.webp',
            'https://mirage-img.b-cdn.net/stickers/meme/91.webp',
            'https://mirage-img.b-cdn.net/stickers/meme/92.webp',
            'https://mirage-img.b-cdn.net/stickers/meme/93.webp',
            'https://mirage-img.b-cdn.net/stickers/meme/94.webp',
        ],
    },
};

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
        max-height: 50vh;
    }
`;

const PopoverHeader = styled.div`
    display: flex;
    align-items: center;
    padding: 0.75rem 1rem;
    border-bottom: 1px solid ${({ theme }) => theme.colors.border};
    gap: 0.5rem;
    flex-wrap: wrap;
`;

const PackTab = styled.button`
    padding: 0.4rem 0.8rem;
    font-size: 0.75rem;
    font-weight: 600;
    border-radius: 6px;
    border: none;
    cursor: pointer;
    transition: background 0.15s ease, color 0.15s ease;
    background: ${({ $active, theme }) =>
        $active
            ? theme.colors.accent
            : theme.colors.panelAlt};
    color: ${({ $active, theme }) => ($active ? theme.colors.text : theme.colors.textSecondary)};

    &:hover {
        background: ${({ $active, theme }) =>
            $active
                ? theme.colors.accent
                : theme.colors.accentSubtle};
        color: ${({ theme }) => theme.colors.text};
    }
`;

const StickerGrid = styled.div`
    display: grid;
    grid-template-columns: repeat(5, 56px);
    grid-auto-rows: 56px;
    gap: 8px;
    padding: 0.75rem;
    overflow-y: auto;
    flex: 1;
    justify-content: center;

    @media (max-width: 600px) {
        grid-template-columns: repeat(4, 56px);
    }
`;

const StickerItem = styled.button`
    width: 56px;
    height: 56px;
    border: none;
    background: ${({ theme }) => theme.colors.panelAlt};
    border-radius: 6px;
    cursor: pointer;
    padding: 4px;
    transition: transform 0.15s ease, background 0.15s ease;
    display: flex;
    align-items: center;
    justify-content: center;
    overflow: hidden;
    flex-shrink: 0;

    &:hover {
        background: ${({ theme }) => theme.colors.accentSubtle};
        border-color: ${({ theme }) => theme.colors.borderStrong};
    }

    img {
        max-width: 100%;
        max-height: 100%;
        width: auto;
        height: auto;
        object-fit: contain;
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

const StickerIcon = () => (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="12" cy="12" r="10" />
        <path d="M8 14s1.5 2 4 2 4-2 4-2" />
        <line x1="9" y1="9" x2="9.01" y2="9" />
        <line x1="15" y1="9" x2="15.01" y2="9" />
    </svg>
);

export default function StickerPicker({ onSelect, disabled = false }) {
    const [isOpen, setIsOpen] = useState(false);
    const [activePack, setActivePack] = useState('meme_stickers');
    const [position, setPosition] = useState({ top: 0, left: 0 });
    const buttonRef = useRef(null);
    const popoverRef = useRef(null);

    const updatePosition = useCallback(() => {
        if (!buttonRef.current) return;
        const rect = buttonRef.current.getBoundingClientRect();
        const popoverHeight = 400;
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

    const handleStickerClick = (url) => {
        onSelect(url);
        setIsOpen(false);
    };

    const packInfo = STICKER_PACKS[activePack];
    const stickers = packInfo.stickers;

    return (
        <PickerWrapper>
            <PickerButton
                ref={buttonRef}
                type="button"
                tabIndex={-1}
                onClick={() => setIsOpen(!isOpen)}
                disabled={disabled}
                aria-label="Stickers"
                title="Stickers"
            >
                <StickerIcon />
            </PickerButton>

            {isOpen && ReactDOM.createPortal(
                <Popover
                    ref={popoverRef}
                    style={{ top: position.top, left: position.left }}
                >
                    <CloseButton onClick={() => setIsOpen(false)} aria-label="Close">
                        ×
                    </CloseButton>
                    <PopoverHeader>
                        {Object.entries(STICKER_PACKS).map(([packId, pack]) => (
                            <PackTab
                                key={packId}
                                $active={activePack === packId}
                                onClick={() => setActivePack(packId)}
                            >
                                {pack.name}
                            </PackTab>
                        ))}
                    </PopoverHeader>
                    <StickerGrid>
                        {stickers.map((url, index) => (
                            <StickerItem
                                key={index}
                                onClick={() => handleStickerClick(url)}
                                aria-label={`Sticker ${index + 1}`}
                            >
                                <img
                                    src={url}
                                    alt=""
                                    loading="lazy"
                                />
                            </StickerItem>
                        ))}
                    </StickerGrid>
                </Popover>,
                document.body
            )}
        </PickerWrapper>
    );
}
