import React from "react";
import styled from "styled-components";
import InlineMedia from "./InlineMedia";

const GalleryFrame = styled.div`
    position: relative;
    display: inline-block;
    max-width: 100%;
`;

const NavButton = styled.button`
    position: absolute;
    top: 50%;
    transform: translateY(-50%);
    width: 32px;
    height: 32px;
    border-radius: 999px;
    border: 1px solid rgba(255, 255, 255, 0.35);
    background: rgba(0, 0, 0, 0.55);
    color: #fff;
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 2;
    cursor: pointer;

    &:hover:not(:disabled) {
        background: rgba(0, 0, 0, 0.7);
    }

    &:disabled {
        opacity: 0.35;
        cursor: not-allowed;
    }

    @media (max-width: 768px) {
        display: none;
    }
`;

const Counter = styled.div`
    position: absolute;
    bottom: 6px;
    right: 6px;
    padding: 2px 6px;
    border-radius: 999px;
    background: rgba(0, 0, 0, 0.6);
    color: #fff;
    font-size: 0.65rem;
    z-index: 2;
`;

export default function MediaGallery({ items, variant, autoPlay = false }) {
    const urls = React.useMemo(
        () => (Array.isArray(items) ? items.filter(Boolean) : []),
        [items]
    );
    const [index, setIndex] = React.useState(0);
    const touchStartXRef = React.useRef(null);

    const isMobile = React.useMemo(() => {
        try {
            const byViewport = (typeof window !== 'undefined') ? (window.innerWidth <= 768) : false;
            const byTouch = (typeof navigator !== 'undefined') ? (navigator.maxTouchPoints > 0) : false;
            return byViewport || byTouch;
        } catch (_) { return false; }
    }, []);

    React.useEffect(() => {
        if (index >= urls.length) setIndex(0);
    }, [urls.length, index]);

    if (!urls.length) return null;
    if (urls.length === 1) {
        return <InlineMedia url={urls[0]} variant={variant} autoPlay={autoPlay} />;
    }

    const goPrev = () => setIndex((prev) => Math.max(0, prev - 1));
    const goNext = () => setIndex((prev) => Math.min(urls.length - 1, prev + 1));

    const handleTouchStart = (e) => {
        if (!isMobile) return;
        const x = e.touches && e.touches[0] ? e.touches[0].clientX : null;
        touchStartXRef.current = (typeof x === 'number') ? x : null;
    };

    const handleTouchEnd = (e) => {
        if (!isMobile) return;
        const startX = touchStartXRef.current;
        touchStartXRef.current = null;
        if (typeof startX !== 'number') return;
        const endX = e.changedTouches && e.changedTouches[0] ? e.changedTouches[0].clientX : null;
        if (typeof endX !== 'number') return;
        const dx = endX - startX;
        const threshold = 40;
        if (Math.abs(dx) < threshold) return;
        if (dx < 0) goNext();
        else goPrev();
    };

    return (
        <GalleryFrame onTouchStart={handleTouchStart} onTouchEnd={handleTouchEnd}>
            <NavButton
                type="button"
                aria-label="Previous media"
                onClick={goPrev}
                disabled={index <= 0}
                style={{ left: '6px' }}
            >
                ‹
            </NavButton>
            <NavButton
                type="button"
                aria-label="Next media"
                onClick={goNext}
                disabled={index >= urls.length - 1}
                style={{ right: '6px' }}
            >
                ›
            </NavButton>
            <InlineMedia url={urls[index]} variant={variant} autoPlay={autoPlay} />
            <Counter>{index + 1}/{urls.length}</Counter>
        </GalleryFrame>
    );
}
