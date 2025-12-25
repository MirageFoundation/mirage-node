import React, { useState, useRef, useEffect, useCallback } from 'react';
import ReactDOM from 'react-dom';
import styled from 'styled-components';

const STICKER_PACKS = {
    meme_stickers: {
        name: 'Meme Stickers',
        stickers: [
            'https://imagedelivery.net/35xU-3qkt-K1MbTH9fOlPQ/8cd7d98a-737b-428a-962b-cdc59a90e800/public',
            'https://imagedelivery.net/35xU-3qkt-K1MbTH9fOlPQ/87322860-c090-4642-bc2d-283f83596800/public',
            'https://imagedelivery.net/35xU-3qkt-K1MbTH9fOlPQ/33248564-bf16-49f5-e98e-9fc55b623100/public',
            'https://imagedelivery.net/35xU-3qkt-K1MbTH9fOlPQ/24346f58-95f5-48c8-d599-166915d4fe00/public',
            'https://imagedelivery.net/35xU-3qkt-K1MbTH9fOlPQ/ff4a5170-813e-478e-0579-10844020e300/public',
            'https://imagedelivery.net/35xU-3qkt-K1MbTH9fOlPQ/0c0268de-14c0-417e-2621-a93432715100/public',
            'https://imagedelivery.net/35xU-3qkt-K1MbTH9fOlPQ/9c1cda93-defb-403b-4c91-845e5e840d00/public',
            'https://imagedelivery.net/35xU-3qkt-K1MbTH9fOlPQ/8d596367-377a-4e4a-dc74-0d6245601b00/public',
            'https://imagedelivery.net/35xU-3qkt-K1MbTH9fOlPQ/7bcbd419-610f-4dde-c879-561ba9c3b000/public',
            'https://imagedelivery.net/35xU-3qkt-K1MbTH9fOlPQ/727b4aea-9c78-4a11-5333-79e5b36e0200/public',
            'https://imagedelivery.net/35xU-3qkt-K1MbTH9fOlPQ/7f2b2e68-c25f-47d8-773e-986d1b89b500/public',
            'https://imagedelivery.net/35xU-3qkt-K1MbTH9fOlPQ/7d26edc9-2c08-4388-ee57-14489b04ec00/public',
            'https://imagedelivery.net/35xU-3qkt-K1MbTH9fOlPQ/42f0eb15-4210-4862-29c1-b903768aab00/public',
            'https://imagedelivery.net/35xU-3qkt-K1MbTH9fOlPQ/f8c9f0b7-4979-4866-1b8a-2fee55333800/public',
            'https://imagedelivery.net/35xU-3qkt-K1MbTH9fOlPQ/7ba438f4-66cf-4c8f-2334-193eb1f39400/public',
            'https://imagedelivery.net/35xU-3qkt-K1MbTH9fOlPQ/8d9104a7-baad-46bb-60f8-b5ce6068ed00/public',
            'https://imagedelivery.net/35xU-3qkt-K1MbTH9fOlPQ/8dfbce36-646b-43a5-d4a0-31f2a5638400/public',
            'https://imagedelivery.net/35xU-3qkt-K1MbTH9fOlPQ/0910992a-516a-4e48-629e-bb69dd1b5900/public',
            'https://imagedelivery.net/35xU-3qkt-K1MbTH9fOlPQ/e121f3ae-8781-4d88-3538-e51beab3cb00/public',
            'https://imagedelivery.net/35xU-3qkt-K1MbTH9fOlPQ/7e5f7e82-4b56-46bb-fb4f-39266c454200/public',
            'https://imagedelivery.net/35xU-3qkt-K1MbTH9fOlPQ/ffa6aa5a-0c94-446e-19e3-88b81b2d2500/public',
            'https://imagedelivery.net/35xU-3qkt-K1MbTH9fOlPQ/0f56adfb-ba23-4ffd-5505-9f82ac834700/public',
            'https://imagedelivery.net/35xU-3qkt-K1MbTH9fOlPQ/ed293456-8398-447c-c6ab-a64f3d2ba000/public',
            'https://imagedelivery.net/35xU-3qkt-K1MbTH9fOlPQ/673a0e22-10a1-4e3f-76fa-4beb4042a100/public',
            'https://imagedelivery.net/35xU-3qkt-K1MbTH9fOlPQ/d263a433-b7e2-4fe3-55f5-a75d44642800/public',
            'https://imagedelivery.net/35xU-3qkt-K1MbTH9fOlPQ/6fc9a174-2962-4c80-ee23-b8cb5e73ba00/public',
            'https://imagedelivery.net/35xU-3qkt-K1MbTH9fOlPQ/97abe402-600c-43d4-0430-a15c62665c00/public',
            'https://imagedelivery.net/35xU-3qkt-K1MbTH9fOlPQ/d1ca3330-905b-4a8b-d39f-7dbf06461900/public',
            'https://imagedelivery.net/35xU-3qkt-K1MbTH9fOlPQ/dbb9f0bc-1342-4e26-c3f2-9d4b84399d00/public',
            'https://imagedelivery.net/35xU-3qkt-K1MbTH9fOlPQ/f5f87afc-3202-4480-f69e-4add9a0ce300/public',
            'https://imagedelivery.net/35xU-3qkt-K1MbTH9fOlPQ/36744778-a993-4878-f235-32255e02ad00/public',
            'https://imagedelivery.net/35xU-3qkt-K1MbTH9fOlPQ/b73d9524-a264-4357-0018-1084909beb00/public',
            'https://imagedelivery.net/35xU-3qkt-K1MbTH9fOlPQ/7920ab8b-9256-4980-97b2-9a00e28f5a00/public',
            'https://imagedelivery.net/35xU-3qkt-K1MbTH9fOlPQ/5e4e6805-1cdd-4c2a-61a4-6fabc54f6700/public',
            'https://imagedelivery.net/35xU-3qkt-K1MbTH9fOlPQ/1fc51ee5-5b74-480f-488a-a4bf9c300a00/public',
            'https://imagedelivery.net/35xU-3qkt-K1MbTH9fOlPQ/8714fca0-0f26-4622-a30c-c5a745063b00/public',
            'https://imagedelivery.net/35xU-3qkt-K1MbTH9fOlPQ/2918b199-6412-4fb9-b561-02a5f65c9800/public',
            'https://imagedelivery.net/35xU-3qkt-K1MbTH9fOlPQ/93497a29-60a8-45ef-358a-6c72a7f34e00/public',
            'https://imagedelivery.net/35xU-3qkt-K1MbTH9fOlPQ/aea431d7-de61-479a-c0cf-3ce3b1681e00/public',
            'https://imagedelivery.net/35xU-3qkt-K1MbTH9fOlPQ/c7a83381-fd12-45c8-95f8-0ff606963300/public',
            'https://imagedelivery.net/35xU-3qkt-K1MbTH9fOlPQ/fc0748ca-7840-4319-41ca-abca5e01f400/public',
            'https://imagedelivery.net/35xU-3qkt-K1MbTH9fOlPQ/cbfb74a0-def6-4514-db1f-91ef5e189800/public',
            'https://imagedelivery.net/35xU-3qkt-K1MbTH9fOlPQ/603fa6e3-7e6d-49a0-11fe-4eb21f49d500/public',
            'https://imagedelivery.net/35xU-3qkt-K1MbTH9fOlPQ/54ba0e05-f49e-4b49-9b21-07aa498fc100/public',
            'https://imagedelivery.net/35xU-3qkt-K1MbTH9fOlPQ/a9916013-7496-40ae-826f-6f0d66506c00/public',
            'https://imagedelivery.net/35xU-3qkt-K1MbTH9fOlPQ/12f77f92-413b-4eed-5b60-e874fa67fe00/public',
            'https://imagedelivery.net/35xU-3qkt-K1MbTH9fOlPQ/69c25edf-ba73-43c8-640a-dcf2a2feb800/public',
            'https://imagedelivery.net/35xU-3qkt-K1MbTH9fOlPQ/e537d6f6-ecfc-46b7-bbe2-8412d8d10300/public',
            'https://imagedelivery.net/35xU-3qkt-K1MbTH9fOlPQ/6905ac4c-2d3e-432d-a061-2583f9792f00/public',
            'https://imagedelivery.net/35xU-3qkt-K1MbTH9fOlPQ/75f13191-db17-4ed9-7ca2-bc6e19a25b00/public',
            'https://imagedelivery.net/35xU-3qkt-K1MbTH9fOlPQ/ca801d5a-dd95-4398-1b58-822fafac1700/public',
            'https://imagedelivery.net/35xU-3qkt-K1MbTH9fOlPQ/4acd8c5f-e7e8-4256-aa84-a1bffdf25900/public',
            'https://imagedelivery.net/35xU-3qkt-K1MbTH9fOlPQ/e4407719-13e7-4a3f-ba91-2ea3304d3c00/public',
            'https://imagedelivery.net/35xU-3qkt-K1MbTH9fOlPQ/b87de547-506e-4fbb-e55e-43a403151700/public',
            'https://imagedelivery.net/35xU-3qkt-K1MbTH9fOlPQ/b1e3a9f7-7db0-45ed-127d-6c9f95ba3100/public',
            'https://imagedelivery.net/35xU-3qkt-K1MbTH9fOlPQ/275f6dc8-ed8a-4984-4574-6cea124aff00/public',
            'https://imagedelivery.net/35xU-3qkt-K1MbTH9fOlPQ/cd2c97bc-40c2-49f0-0c55-fc4999c9bc00/public',
            'https://imagedelivery.net/35xU-3qkt-K1MbTH9fOlPQ/1b3ecb86-4b45-453d-eb55-676f76ac6000/public',
            'https://imagedelivery.net/35xU-3qkt-K1MbTH9fOlPQ/3b9c1cc3-2c7b-4130-0368-159288f11600/public',
            'https://imagedelivery.net/35xU-3qkt-K1MbTH9fOlPQ/0b84724a-5965-4f83-a217-b79303ce0000/public',
            'https://imagedelivery.net/35xU-3qkt-K1MbTH9fOlPQ/46e8ab97-5181-434c-15e9-413867a28100/public',
            'https://imagedelivery.net/35xU-3qkt-K1MbTH9fOlPQ/8f5b841f-fb40-4cee-58cc-92318b62cf00/public',
            'https://imagedelivery.net/35xU-3qkt-K1MbTH9fOlPQ/70f86e73-b2f8-4d8a-f5b6-975c64b99b00/public',
            'https://imagedelivery.net/35xU-3qkt-K1MbTH9fOlPQ/695189a1-a6a3-4db4-74f1-d55f0db07900/public',
            'https://imagedelivery.net/35xU-3qkt-K1MbTH9fOlPQ/27e32049-870c-45f2-4a52-ecbb5ba0c900/public',
            'https://imagedelivery.net/35xU-3qkt-K1MbTH9fOlPQ/ab526cf6-7321-45f7-b9aa-ef1022b15800/public',
            'https://imagedelivery.net/35xU-3qkt-K1MbTH9fOlPQ/85203c6e-4cec-4865-ac93-55e2d547ea00/public',
            'https://imagedelivery.net/35xU-3qkt-K1MbTH9fOlPQ/a86fd7ab-b247-4ff8-2fa9-fd52ada3de00/public',
            'https://imagedelivery.net/35xU-3qkt-K1MbTH9fOlPQ/fa05de42-1018-41f5-9f1f-7e506fedf600/public',
            'https://imagedelivery.net/35xU-3qkt-K1MbTH9fOlPQ/53f6d3bc-1156-4e03-6496-4ed59c15dd00/public',
            'https://imagedelivery.net/35xU-3qkt-K1MbTH9fOlPQ/e41bd710-8870-4acd-8c11-4df6615f4900/public',
            'https://imagedelivery.net/35xU-3qkt-K1MbTH9fOlPQ/6eda51b4-efae-46ef-349c-090b5c544400/public',
            'https://imagedelivery.net/35xU-3qkt-K1MbTH9fOlPQ/0d1b8426-af77-4553-7ea2-6fb84b6c9400/public',
            'https://imagedelivery.net/35xU-3qkt-K1MbTH9fOlPQ/48129047-7bbd-4ea3-0e9a-f8cbfc10cc00/public',
            'https://imagedelivery.net/35xU-3qkt-K1MbTH9fOlPQ/d60908a5-bf4c-4353-3681-b2422cd62d00/public',
            'https://imagedelivery.net/35xU-3qkt-K1MbTH9fOlPQ/a3570f04-24a6-4e0d-2d07-15d2c5bf2e00/public',
            'https://imagedelivery.net/35xU-3qkt-K1MbTH9fOlPQ/8bf7a31f-74d0-44f2-c1bb-666f0b949e00/public',
            'https://imagedelivery.net/35xU-3qkt-K1MbTH9fOlPQ/46ea1c67-1cb6-4ecd-0335-849a5203ec00/public',
            'https://imagedelivery.net/35xU-3qkt-K1MbTH9fOlPQ/2a0835f0-4ec8-409b-3e67-27c68ea7a200/public',
            'https://imagedelivery.net/35xU-3qkt-K1MbTH9fOlPQ/20ae2765-3e8d-48e7-3756-ed5836eebe00/public',
            'https://imagedelivery.net/35xU-3qkt-K1MbTH9fOlPQ/b02a3bf8-3132-46cc-d6f9-dc4348946100/public',
            'https://imagedelivery.net/35xU-3qkt-K1MbTH9fOlPQ/3ae27f5f-a57a-495f-c66c-6d48556c9700/public',
            'https://imagedelivery.net/35xU-3qkt-K1MbTH9fOlPQ/3d553814-c80b-44ee-fe43-3f1c5e9b0400/public',
            'https://imagedelivery.net/35xU-3qkt-K1MbTH9fOlPQ/8999040b-1b98-48b8-6061-d288cceb2f00/public',
            'https://imagedelivery.net/35xU-3qkt-K1MbTH9fOlPQ/1f510df5-48ab-488f-dd66-5f180c164b00/public',
            'https://imagedelivery.net/35xU-3qkt-K1MbTH9fOlPQ/bc787835-8c55-41d1-5753-6798fa8a8e00/public',
            'https://imagedelivery.net/35xU-3qkt-K1MbTH9fOlPQ/f877fc9d-f0ac-472b-10fc-ef47cd678600/public',
            'https://imagedelivery.net/35xU-3qkt-K1MbTH9fOlPQ/554b7d83-4bb2-488e-5f2f-25bf7097ae00/public',
            'https://imagedelivery.net/35xU-3qkt-K1MbTH9fOlPQ/579f7704-0fe0-44dd-747c-7e695dfa5a00/public',
            'https://imagedelivery.net/35xU-3qkt-K1MbTH9fOlPQ/3352d81f-8e2b-4c04-a538-e5bc2efb7000/public',
            'https://imagedelivery.net/35xU-3qkt-K1MbTH9fOlPQ/2c94e085-a04b-4a73-dfa9-6ed9b116e700/public',
            'https://imagedelivery.net/35xU-3qkt-K1MbTH9fOlPQ/53949631-593d-4b7f-6342-7d703e913700/public',
            'https://imagedelivery.net/35xU-3qkt-K1MbTH9fOlPQ/9f4cc55a-10f1-46e4-4526-60a7f873cc00/public',
            'https://imagedelivery.net/35xU-3qkt-K1MbTH9fOlPQ/84243bbf-ef00-4207-b04d-6678ecdf1300/public',
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

const Popover = styled.div`
    position: fixed;
    z-index: 10100;
    background: ${({ theme }) => theme?.colors?.panel || '#1a1d21'};
    border: 1px solid ${({ theme }) => theme?.colors?.border || '#333'};
    border-radius: 12px;
    box-shadow: 0 8px 32px rgba(0, 0, 0, 0.5);
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
    border-bottom: 1px solid ${({ theme }) => theme?.colors?.border || '#333'};
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
    transition: all 0.15s ease;
    background: ${({ $active, theme }) =>
        $active
            ? 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)'
            : (theme?.colors?.panelAlt || '#2a2d31')};
    color: ${({ $active }) => ($active ? '#fff' : '#aaa')};

    &:hover {
        background: ${({ $active }) =>
            $active
                ? 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)'
                : 'rgba(102, 126, 234, 0.2)'};
        color: #fff;
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
    background: ${({ theme }) => theme?.colors?.panelAlt || '#2a2d31'};
    border-radius: 8px;
    cursor: pointer;
    padding: 4px;
    transition: all 0.15s ease;
    display: flex;
    align-items: center;
    justify-content: center;
    overflow: hidden;
    flex-shrink: 0;

    &:hover {
        background: rgba(102, 126, 234, 0.25);
        transform: scale(1.08);
    }

    &:active {
        transform: scale(0.95);
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
    background: #dc2626;
    color: #ffffff;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 1rem;
    line-height: 1;
    transition: all 0.15s ease;
    z-index: 1;
    box-shadow: 0 2px 4px rgba(0,0,0,0.4);

    &:hover {
        background: #b91c1c;
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
