import React from "react";
import styled from "styled-components";
import InlineMedia from "./InlineMedia";

/* Match InlineMedia sizing constants */
const MAX_DISPLAY_W = 600;
const MAX_DISPLAY_H_ROOT = 600;
const MAX_DISPLAY_H_COMMENT = 225;

function isImageUrl(url) {
    try {
        const u = new URL(url);
        const host = u.hostname.toLowerCase();
        const p = u.pathname.toLowerCase();
        return host.endsWith('imagedelivery.net') || /\.(png|jpe?g|gif|webp|bmp|avif)$/i.test(p);
    } catch (_) { return false; }
}

/* ── styled ─────────────────────────────────────────────── */

const GalleryFrame = styled.div`
    position: relative;
    width: fit-content;
    max-width: 100%;
`;

/** Flex stage that keeps a stable min-height so arrows don't jump. */
const Stage = styled.div`
    display: flex;
    align-items: center;
    justify-content: center;
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
    pointer-events: none;
`;

/* ── component ──────────────────────────────────────────── */

export default function MediaGallery({ items, variant, autoPlay = false }) {
    const urls = React.useMemo(
        () => (Array.isArray(items) ? items.filter(Boolean) : []),
        [items]
    );
    const [index, setIndex] = React.useState(0);
    const touchStartXRef = React.useRef(null);

    /* ── stable height: only grows, never shrinks ── */
    const [stableHeight, setStableHeight] = React.useState(0);
    const slideRef = React.useRef(null);
    const maxH = variant === 'root_post' ? MAX_DISPLAY_H_ROOT : MAX_DISPLAY_H_COMMENT;

    // Preload every image URL and pre-compute its display height.
    // This makes navigation instant and lets us know the tallest item
    // before the user ever clicks an arrow.
    React.useEffect(() => {
        urls.forEach(url => {
            if (!isImageUrl(url)) return;
            const img = new Image();
            img.onload = () => {
                const r = img.naturalWidth / img.naturalHeight;
                let w = maxH * r;
                if (w > img.naturalWidth) w = img.naturalWidth;
                if (w > MAX_DISPLAY_W) w = MAX_DISPLAY_W;
                const h = w / r;
                setStableHeight(prev => Math.max(prev, Math.round(h)));
            };
            img.src = url;
        });
    }, [urls, maxH]);

    // ResizeObserver on the active slide: handles videos / iframes
    // whose height we can't precompute, and corrects for container-width
    // differences between the precompute estimate and real layout.
    React.useEffect(() => {
        const el = slideRef.current;
        if (!el) return;
        const ro = new ResizeObserver(entries => {
            for (const entry of entries) {
                const h = Math.round(entry.contentRect.height);
                if (h > 0) setStableHeight(prev => Math.max(prev, h));
            }
        });
        ro.observe(el);
        return () => ro.disconnect();
    }, [index]);

    /* ── mobile detection ── */
    const isMobile = React.useMemo(() => {
        try {
            const byViewport = (typeof window !== 'undefined') ? (window.innerWidth <= 768) : false;
            const byTouch = (typeof navigator !== 'undefined') ? (navigator.maxTouchPoints > 0) : false;
            return byViewport || byTouch;
        } catch (_) { return false; }
    }, []);

    /* ── bounds check ── */
    React.useEffect(() => {
        if (index >= urls.length) setIndex(0);
    }, [urls.length, index]);

    /* ── early returns ── */
    if (!urls.length) return null;
    if (urls.length === 1) {
        return <InlineMedia url={urls[0]} variant={variant} autoPlay={autoPlay} />;
    }

    /* ── navigation ── */
    const goPrev = () => setIndex(prev => Math.max(0, prev - 1));
    const goNext = () => setIndex(prev => Math.min(urls.length - 1, prev + 1));

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
        if (Math.abs(dx) < 40) return;
        if (dx < 0) goNext();
        else goPrev();
    };

    /* ── render ── */
    return (
        <GalleryFrame onTouchStart={handleTouchStart} onTouchEnd={handleTouchEnd}>
            <NavButton
                type="button"
                aria-label="Previous media"
                onClick={goPrev}
                disabled={index <= 0}
                style={{ left: '6px' }}
            >
                &#8249;
            </NavButton>
            <NavButton
                type="button"
                aria-label="Next media"
                onClick={goNext}
                disabled={index >= urls.length - 1}
                style={{ right: '6px' }}
            >
                &#8250;
            </NavButton>

            <Stage style={stableHeight ? { minHeight: `${stableHeight}px` } : undefined}>
                <div ref={slideRef}>
                    <InlineMedia
                        key={urls[index]}
                        url={urls[index]}
                        variant={variant}
                        autoPlay={autoPlay}
                    />
                </div>
            </Stage>

            <Counter>{index + 1}/{urls.length}</Counter>
        </GalleryFrame>
    );
}
