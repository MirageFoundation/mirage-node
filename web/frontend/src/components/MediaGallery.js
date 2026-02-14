import React from "react";
import styled from "styled-components";
import InlineMedia from "./InlineMedia";

function isImageUrl(url) {
    try {
        const u = new URL(url);
        const host = u.hostname.toLowerCase();
        const p = u.pathname.toLowerCase();
        return host.endsWith('imagedelivery.net') || /\.(png|jpe?g|gif|webp|bmp|avif)$/i.test(p);
    } catch (_) { return false; }
}

/* ── styled ─────────────────────────────────────────────── */

const NavBar = styled.div`
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 4px 0 6px;
    font-size: 0.85rem;
    font-weight: 700;
    color: ${({ theme }) => theme?.colors?.textSecondary || '#bbb'};
    user-select: none;
`;

const ArrowBtn = styled.button`
    background: none;
    border: none;
    color: ${({ theme }) => theme?.colors?.link || '#ccc'};
    cursor: pointer;
    font-size: 1.3rem;
    padding: 2px 6px;
    line-height: 1;
    border-radius: 4px;
    transition: background 0.08s, color 0.08s, transform 0.06s;

    &:hover {
        color: #fff;
        background: rgba(255, 255, 255, 0.1);
    }

    &:active {
        color: #fff;
        background: rgba(255, 255, 255, 0.2);
        transform: scale(0.9);
    }
`;

/* ── component ──────────────────────────────────────────── */

export default function MediaGallery({ items, variant, autoPlay = false }) {
    const urls = React.useMemo(
        () => (Array.isArray(items) ? items.filter(Boolean) : []),
        [items]
    );
    const [index, setIndex] = React.useState(0);
    const touchStartXRef = React.useRef(null);
    const scrollYRef = React.useRef(0);

    // Track which items have been visited so we mount them lazily
    // but never unmount them (preserving resize state).
    const [mounted, setMounted] = React.useState(() => new Set([0]));

    const isMobile = React.useMemo(() => {
        try {
            const byViewport = (typeof window !== 'undefined') ? (window.innerWidth <= 768) : false;
            const byTouch = (typeof navigator !== 'undefined') ? (navigator.maxTouchPoints > 0) : false;
            return byViewport || byTouch;
        } catch (_) { return false; }
    }, []);

    // Preload all image URLs so navigation is instant
    React.useEffect(() => {
        urls.forEach(url => {
            if (!isImageUrl(url)) return;
            const img = new Image();
            img.src = url;
        });
    }, [urls]);

    React.useEffect(() => {
        if (index >= urls.length) setIndex(0);
    }, [urls.length, index]);

    // Restore scroll position after index change to prevent viewport jump
    React.useLayoutEffect(() => {
        window.scrollTo(0, scrollYRef.current);
    }, [index]);

    if (!urls.length) return null;
    if (urls.length === 1) {
        return <InlineMedia url={urls[0]} variant={variant} autoPlay={autoPlay} />;
    }

    /* ── wrapping navigation (saves scroll before state change) ── */
    const navigate = (newIndex) => {
        scrollYRef.current = window.scrollY;
        setMounted(prev => { const n = new Set(prev); n.add(newIndex); return n; });
        setIndex(newIndex);
    };
    const goPrev = () => navigate(index <= 0 ? urls.length - 1 : index - 1);
    const goNext = () => navigate(index >= urls.length - 1 ? 0 : index + 1);

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

    return (
        <div onTouchStart={handleTouchStart} onTouchEnd={handleTouchEnd}>
            <NavBar>
                <span>Gallery:</span>
                <ArrowBtn type="button" onClick={goPrev} aria-label="Previous media">&#8592;</ArrowBtn>
                <span>{index + 1} of {urls.length}</span>
                <ArrowBtn type="button" onClick={goNext} aria-label="Next media">&#8594;</ArrowBtn>
            </NavBar>
            {urls.map((url, i) => {
                if (!mounted.has(i)) return null;
                return (
                    <div key={url} style={i === index ? undefined : { display: 'none' }}>
                        <InlineMedia url={url} variant={variant} autoPlay={i === index && autoPlay} />
                    </div>
                );
            })}
        </div>
    );
}
