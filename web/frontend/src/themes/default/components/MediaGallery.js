import React from "react";
import styled from "styled-components";
import InlineMedia from "./InlineMedia";

/* ── styled ─────────────────────────────────────────────── */

const NavBar = styled.div`
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 4px 0 6px;
    font-size: 0.85rem;
    font-weight: 700;
    color: ${({ theme }) => theme.colors.textSecondary};
    user-select: none;
`;

const ArrowBtn = styled.button`
    background: none;
    border: none;
    color: ${({ theme }) => theme.colors.link};
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

// Hidden items: invisible, 0 height (no layout impact), but still
// laid out horizontally so InlineMedia can measure parent width and
// the browser fetches <img> src for real preloading.
const HIDDEN_STYLE = { visibility: 'hidden', height: 0, overflow: 'hidden' };

/* ── component ──────────────────────────────────────────── */

export default function MediaGallery({ items, variant, autoPlay = false, mediaMeta = null }) {
    const urls = React.useMemo(
        () => (Array.isArray(items) ? items.filter(Boolean) : []),
        [items]
    );
    const metaArr = Array.isArray(mediaMeta) ? mediaMeta : [];
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
        return <InlineMedia url={urls[0]} variant={variant} autoPlay={autoPlay} mediaMeta={metaArr[0] || null} />;
    }

    /* ── navigation ── */
    const goPrev = () => setIndex(prev => (prev <= 0 ? urls.length - 1 : prev - 1));
    const goNext = () => setIndex(prev => (prev >= urls.length - 1 ? 0 : prev + 1));

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
            {urls.map((url, i) => (
                <div key={url} style={i === index ? undefined : HIDDEN_STYLE}>
                    <InlineMedia url={url} variant={variant} autoPlay={i === index && autoPlay} mediaMeta={metaArr[i] || null} />
                </div>
            ))}
        </div>
    );
}
