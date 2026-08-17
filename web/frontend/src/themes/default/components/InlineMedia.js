import React from "react";
import styled, { useTheme } from "styled-components";
import { normalizeRedgifsToMp4, extractRedgifsId, redgifsCanonicalWatchUrl, extractRumbleId, buildRumbleEmbedUrl } from "../../../utils/media";
import { classifyMediaUrl } from "../../../utils/mediaPolicy";

const IFRAME_SANDBOX = 'allow-scripts allow-same-origin allow-presentation';

function buildRedgifsEmbedUrl(id, autoPlay) {
    const params = new URLSearchParams({ muted: '1', loop: '1', controls: '1' });
    if (autoPlay) params.set('autoplay', '1');
    return `https://www.redgifs.com/ifr/${id}?${params.toString()}`;
}

function youtubeAllow(autoPlay) {
    return autoPlay
        ? 'accelerometer; autoplay; encrypted-media; picture-in-picture; fullscreen'
        : 'accelerometer; encrypted-media; picture-in-picture; fullscreen';
}

function extractYoutubeId(rawUrl) {
    try {
        if (!rawUrl) return null;
        const u = new URL(rawUrl);
        const host = (u.hostname || '').toLowerCase();
        if (host === 'www.youtube.com' || host === 'youtube.com' || host === 'm.youtube.com') {
            if (u.pathname === '/watch') {
                const params = new URLSearchParams(u.search);
                return params.get('v') || null;
            }
            if (u.pathname.startsWith('/embed/') || u.pathname.startsWith('/v/')) {
                const parts = u.pathname.split('/');
                return parts[2] ? parts[2].split('?')[0] : null;
            }
            if (u.pathname.startsWith('/shorts/')) {
                const parts = u.pathname.split('/');
                return parts[2] ? parts[2].split('?')[0] : null;
            }
        }
        if (host === 'youtu.be' || host === 'www.youtu.be') {
            const path = (u.pathname || '').replace(/^\//, '');
            return path ? path.split('/')[0].split('?')[0] : null;
        }
    } catch (_) { }
    return null;
}

const StyledLink = styled.a`
    color: ${({ theme }) => theme.colors.link};
    text-decoration: underline;
    &:hover {
        color: ${({ theme }) => theme.colors.linkHover};
    }
    &:visited {
        color: ${({ theme }) => theme.colors.link};
    }
`;

function normalizeNewlines(text) {
    if (!text || typeof text !== 'string') return text;
    return text.replace(/\n{3,}/g, '\n\n');
}

function sanitizeUrlForLink(raw) {
    try {
        const u = new URL(raw);
        return redgifsCanonicalWatchUrl(u.toString());
    } catch (_) {
        const match = String(raw || '').match(
            /^(https?:\/\/[^\s<>"']*?(?:\.(?:m3u8|mp4|webm|ogv|mov|mkv|gifv|png|jpg|jpeg|gif|webp|bmp|avif))(?:[?#][^\s<>"']*)?)/i
        );
        if (match && match[1]) return redgifsCanonicalWatchUrl(match[1]);
        const generic = String(raw || '').match(/^(https?:\/\/[^\s<>"']+)/i);
        const base = generic && generic[1] ? generic[1] : raw;
        return redgifsCanonicalWatchUrl(base);
    }
}

function linkifyText(text) {
    if (!text || typeof text !== 'string') return text;
    const normalized = normalizeNewlines(text);
    const urlRegex = /(https?:\/\/[^\s<>"']+)/g;
    const parts = [];
    let lastIndex = 0;
    let match;
    let keyCounter = 0;
    while ((match = urlRegex.exec(normalized)) !== null) {
        if (match.index > lastIndex) {
            parts.push(normalized.slice(lastIndex, match.index));
        }
        const url = sanitizeUrlForLink(match[0]);
        parts.push(
            <StyledLink key={`link-${keyCounter++}`} href={url} target="_blank" rel="noopener noreferrer">
                {url}
            </StyledLink>
        );
        lastIndex = match.index + url.length;
    }
    if (lastIndex < normalized.length) {
        parts.push(normalized.slice(lastIndex));
    }
    return parts.length > 1 ? parts : (parts.length === 1 ? parts[0] : normalized);
}

const MAX_INITIAL_HEIGHT_ROOT = 600;
const MAX_INITIAL_HEIGHT_COMMENT = 225;
const MAX_INITIAL_WIDTH = 600;



function InlineMediaBody({ url, variant, autoPlay = false, mediaMeta = null }) {
    const theme = useTheme();
    const capMaxVideoWidth = theme.layout.maxVideoWidth;
    const [naturalWidth, setNaturalWidth] = React.useState((mediaMeta && mediaMeta.w) || 0);
    const [naturalHeight, setNaturalHeight] = React.useState((mediaMeta && mediaMeta.h) || 0);
    const [displayWidth, setDisplayWidth] = React.useState(null);
    const [containerMaxWidth, setContainerMaxWidth] = React.useState(0);
    const wrapperRef = React.useRef(null);
    const dragStartXRef = React.useRef(0);
    const dragStartWidthRef = React.useRef(0);
    const isDraggingRef = React.useRef(false);
    const hasManuallyResizedRef = React.useRef(false);
    const mountedRef = React.useRef(true);
    const videoRef = React.useRef(null);
    const hlsInstanceRef = React.useRef(null);
    const retryTimerRef = React.useRef(null);
    const [isProcessing, setIsProcessing] = React.useState(false);
    const [loadFailed, setLoadFailed] = React.useState(false);

    const isMobile = React.useMemo(() => {
        try {
            const byViewport = (typeof window !== 'undefined') ? (window.innerWidth <= 768) : false;
            const byTouch = (typeof navigator !== 'undefined') ? (navigator.maxTouchPoints > 0) : false;
            return byViewport || byTouch;
        } catch (_) { return false; }
    }, []);

    React.useEffect(() => {
        mountedRef.current = true;
        return () => { mountedRef.current = false; };
    }, []);

    React.useEffect(() => {
        const updateContainerWidth = () => {
            try {
                const el = wrapperRef.current;
                const parent = el?.parentElement;
                if (parent) {
                    setContainerMaxWidth(parent.clientWidth);
                }
            } catch (_) { }
        };
        updateContainerWidth();
        window.addEventListener('resize', updateContainerWidth);
        return () => window.removeEventListener('resize', updateContainerWidth);
    }, []);

    const computeInitialWidth = React.useCallback(() => {
        if (!naturalWidth || !naturalHeight) return MAX_INITIAL_WIDTH;
        const maxHeight = variant === 'root_post' ? MAX_INITIAL_HEIGHT_ROOT : MAX_INITIAL_HEIGHT_COMMENT;
        const maxWidth = Math.min(
            capMaxVideoWidth || MAX_INITIAL_WIDTH,
            containerMaxWidth || MAX_INITIAL_WIDTH
        );
        const scale = Math.min(
            1,
            maxWidth / naturalWidth,
            maxHeight / naturalHeight
        );
        return naturalWidth * scale;
    }, [naturalWidth, naturalHeight, containerMaxWidth, variant, capMaxVideoWidth]);

    React.useEffect(() => {
        if (naturalWidth && naturalHeight && displayWidth === null) {
            setDisplayWidth(computeInitialWidth());
        }
    }, [naturalWidth, naturalHeight, displayWidth, computeInitialWidth]);

    const onPointerDown = (e) => {
        if (isMobile) return;
        e.preventDefault();
        isDraggingRef.current = true;
        hasManuallyResizedRef.current = true;
        dragStartXRef.current = e.clientX;
        dragStartWidthRef.current = displayWidth || computeInitialWidth();
        try { e.currentTarget.setPointerCapture(e.pointerId); } catch (_) { }
    };

    const onPointerMove = (e) => {
        if (!isDraggingRef.current || isMobile) return;
        e.preventDefault();
        const dx = e.clientX - dragStartXRef.current;
        // Exponential feel: use a power curve on the delta
        const sign = dx >= 0 ? 1 : -1;
        const expDx = sign * Math.pow(Math.abs(dx), 1.05);
        let newWidth = dragStartWidthRef.current + expDx;
        const minWidth = 50;
        // Allow drag-to-zoom to grow up to the viewport's right edge
        // rather than being capped by the narrow post/feed column
        // (FeedCol is 820px on desktop in default). We measure the
        // image's current left offset so the image can fill the space
        // from wherever it starts to the right edge of the viewport —
        // matching bluemoon's behaviour.
        let viewportMax;
        if (typeof window !== 'undefined') {
            let leftOffset = 0;
            try {
                const rect = wrapperRef.current?.getBoundingClientRect();
                if (rect) leftOffset = Math.max(0, rect.left);
            } catch (_) { }
            viewportMax = Math.max(0, window.innerWidth - leftOffset - 16);
        } else {
            viewportMax = 1000;
        }
        let maxWidth = viewportMax;
        // NOTE: intentionally do NOT clamp drag-to-zoom to
        // `theme.layout.maxVideoWidth` — that token sets the INITIAL
        // render width cap only. Once the user starts drag-zooming we
        // want the full viewport available (matches bluemoon).
        if (newWidth < minWidth) newWidth = minWidth;
        if (newWidth > maxWidth) newWidth = maxWidth;
        setDisplayWidth(newWidth);
    };

    const onPointerUp = (e) => {
        if (isMobile) return;
        e.preventDefault();
        isDraggingRef.current = false;
        try { e.currentTarget.releasePointerCapture(e.pointerId); } catch (_) { }
    };

    const onPointerCancel = (e) => {
        if (isMobile) return;
        isDraggingRef.current = false;
        try { e.currentTarget.releasePointerCapture(e.pointerId); } catch (_) { }
    };

    // HLS video player setup for Cloudflare Stream
    React.useEffect(() => {
        let videoUid = null;
        let hlsSource = null;
        try {
            const resolved = normalizeRedgifsToMp4(url);
            const u = new URL(resolved, window.location.origin);
            const host = u.hostname.toLowerCase();
            const isIframeStream = host === 'iframe.cloudflarestream.com';
            const isStreamDomain = isIframeStream || host.endsWith('cloudflarestream.com') || host.endsWith('videodelivery.net');
            if (isStreamDomain) {
                const match = u.pathname.match(/^\/?([^/]+)/);
                videoUid = match ? match[1] : null;
                if (videoUid) hlsSource = `/api/stream_proxy/${videoUid}`;
            } else if (u.pathname.toLowerCase().endsWith('.m3u8')) {
                // Generic HLS (e.g. Bunny Stream): play the manifest directly.
                hlsSource = u.href;
            }
        } catch (_) { }

        if (!videoRef.current || !hlsSource) return;

        const video = videoRef.current;
        const hlsUrl = hlsSource;

        const initVideo = () => {
            if (!videoRef.current) return;
            const supportsNativeHLS = video.canPlayType('application/vnd.apple.mpegurl') ||
                video.canPlayType('application/x-mpegURL');
            if (supportsNativeHLS) {
                const source = document.createElement('source');
                source.src = hlsUrl;
                source.type = 'application/vnd.apple.mpegurl';
                video.appendChild(source);
                video.load();
            } else {
                video.removeAttribute('src');
                video.querySelectorAll('source').forEach(src => src.remove());
                video.load();

                const loadHls = async () => {
                    try {
                        const hlsModule = await import('hls.js');
                        const Hls = hlsModule.default || hlsModule;
                        if (Hls.isSupported()) {
                            const hlsInstance = new Hls({
                                enableWorker: true,
                                lowLatencyMode: false,
                                backBufferLength: 90,
                                xhrSetup: (xhr) => { xhr.withCredentials = false; }
                            });
                            hlsInstanceRef.current = hlsInstance;
                            hlsInstance.loadSource(hlsUrl);
                            hlsInstance.attachMedia(video);

                            const retries = { count: 0, max: 20 };
                            const scheduleRetry = () => {
                                if (!mountedRef.current || !hlsInstanceRef.current) return;
                                if (retries.count >= retries.max) {
                                    setIsProcessing(false);
                                    setLoadFailed(true);
                                    return;
                                }
                                const delayMs = Math.min(5000, 1000 * Math.pow(1.3, retries.count));
                                retries.count += 1;
                                if (mountedRef.current) setIsProcessing(true);
                                if (retryTimerRef.current) clearTimeout(retryTimerRef.current);
                                retryTimerRef.current = setTimeout(() => {
                                    if (!mountedRef.current || !hlsInstanceRef.current) return;
                                    hlsInstanceRef.current.stopLoad();
                                    hlsInstanceRef.current.loadSource(hlsUrl);
                                    hlsInstanceRef.current.startLoad();
                                }, delayMs);
                            };

                            hlsInstance.on(Hls.Events.ERROR, (event, data) => {
                                if (data.fatal) {
                                    if (data.type === Hls.ErrorTypes.NETWORK_ERROR) {
                                        scheduleRetry();
                                    } else if (data.type === Hls.ErrorTypes.MEDIA_ERROR) {
                                        hlsInstance.recoverMediaError();
                                    } else {
                                        hlsInstance.destroy();
                                        if (mountedRef.current) {
                                            setIsProcessing(false);
                                            setLoadFailed(true);
                                        }
                                    }
                                }
                            });
                        }
                    } catch (_) { }
                };
                loadHls();
            }
        };

        const timeoutId = setTimeout(initVideo, 100);
        return () => {
            clearTimeout(timeoutId);
            if (retryTimerRef.current) clearTimeout(retryTimerRef.current);
            if (hlsInstanceRef.current) {
                try {
                    hlsInstanceRef.current.stopLoad();
                    hlsInstanceRef.current.detachMedia();
                    hlsInstanceRef.current.destroy();
                    hlsInstanceRef.current = null;
                } catch (_) { }
            }
        };
    }, [url]);

    try {
        const redgifsId = extractRedgifsId(url);
        if (redgifsId) {
            const embedUrl = buildRedgifsEmbedUrl(redgifsId, autoPlay);
            const aspectPadding = '56.25%'; // 16:9 default
            return (
                <div style={{ position: 'relative', width: '100%', paddingTop: aspectPadding, borderRadius: '4px', overflow: 'hidden' }}>
                    <iframe
                        src={embedUrl}
                        title="Redgifs embed"
                        allow={autoPlay ? 'fullscreen; autoplay' : 'fullscreen'}
                        allowFullScreen
                        referrerPolicy="no-referrer"
                        sandbox={IFRAME_SANDBOX}
                        loading="lazy"
                        frameBorder="0"
                        scrolling="no"
                        style={{ position: 'absolute', top: 0, left: 0, width: '100%', height: '100%' }}
                    />
                </div>
            );
        }

        // YouTube embed — referrerPolicy must send an origin. YouTube Error 153
        // ("Video player configuration error") is returned when Referer is stripped
        // (document or iframe Referrer-Policy: no-referrer).
        const youtubeId = extractYoutubeId(url);
        if (youtubeId) {
            const embedUrl = autoPlay
                ? `https://www.youtube.com/embed/${youtubeId}?rel=0&autoplay=1&mute=1`
                : `https://www.youtube.com/embed/${youtubeId}?rel=0`;
            const aspectPadding = '56.25%'; // 16:9 default
            return (
                <div style={{ position: 'relative', width: '100%', paddingTop: aspectPadding, borderRadius: '4px', overflow: 'hidden' }}>
                    <iframe
                        src={embedUrl}
                        title="YouTube video"
                        allow={youtubeAllow(autoPlay)}
                        allowFullScreen
                        referrerPolicy="strict-origin-when-cross-origin"
                        sandbox={IFRAME_SANDBOX}
                        loading="lazy"
                        frameBorder="0"
                        style={{ position: 'absolute', top: 0, left: 0, width: '100%', height: '100%' }}
                    />
                </div>
            );
        }

        // Rumble embed. The embed id has to come from the indexer, which asks
        // Rumble for it: watch ids and embed ids are separate namespaces that
        // collide, so an id lifted from the posted URL frames a stranger's
        // video rather than failing. Link out until it has been resolved.
        const rumbleId = extractRumbleId(url);
        if (rumbleId) {
            const rumbleEmbedId = (mediaMeta && typeof mediaMeta.embed === 'string') ? mediaMeta.embed : null;
            if (!rumbleEmbedId) {
                return (
                    <a
                        href={url}
                        target="_blank"
                        rel="noopener noreferrer nofollow"
                        style={{ display: 'block', padding: '1rem', background: '#222', borderRadius: '4px', color: '#fff', textDecoration: 'none' }}
                    >
                        Watch on Rumble
                    </a>
                );
            }
            const embedUrl = buildRumbleEmbedUrl(rumbleEmbedId, autoPlay);
            const aspectPadding = '56.25%'; // 16:9 default
            return (
                <div style={{ position: 'relative', width: '100%', paddingTop: aspectPadding, borderRadius: '4px', overflow: 'hidden' }}>
                    <iframe
                        src={embedUrl}
                        title="Rumble video"
                        allow={youtubeAllow(autoPlay)}
                        allowFullScreen
                        referrerPolicy="no-referrer"
                        sandbox={IFRAME_SANDBOX}
                        loading="lazy"
                        frameBorder="0"
                        style={{ position: 'absolute', top: 0, left: 0, width: '100%', height: '100%' }}
                    />
                </div>
            );
        }

        const resolved = normalizeRedgifsToMp4(url);
        const u = new URL(resolved, window.location.origin);
        const scheme = u.protocol.toLowerCase().replace(':', '');
        if (scheme !== 'http' && scheme !== 'https') throw new Error('Not http/https');

        const p = u.pathname.toLowerCase();
        const host = u.hostname.toLowerCase();
        const isImgDomain = host.endsWith('imagedelivery.net');
        const isImgExt = /\.(png|jpe?g|gif|webp|bmp|avif)$/i.test(p);
        const isImg = isImgDomain || isImgExt;
        const isIframeStream = host === 'iframe.cloudflarestream.com';
        const isStreamDomain = isIframeStream || host.endsWith('cloudflarestream.com') || host.endsWith('videodelivery.net');
        const isHlsExt = /\.m3u8$/i.test(p);
        const isVidExt = /\.(mp4|webm|ogv|mov|mkv|gifv)$/i.test(p);
        const isVid = isStreamDomain || isVidExt || isHlsExt;

        const currentWidth = displayWidth || computeInitialWidth();

        const resizeHandlers = isMobile ? {} : {
            onPointerDown,
            onPointerMove,
            onPointerUp,
            onPointerCancel,
            onDragStart: (e) => e.preventDefault()
        };

        const maxHeight = variant === 'root_post' ? MAX_INITIAL_HEIGHT_ROOT : MAX_INITIAL_HEIGHT_COMMENT;
        const userResized = hasManuallyResizedRef.current;
        const dimensionsKnown = naturalWidth && naturalHeight;
        const mediaStyle = {
            width: dimensionsKnown ? `${currentWidth}px` : 'auto',
            // When the user has drag-resized, let the image break out of
            // the narrow post column (the global `img { max-width: 100% }`
            // rule would otherwise cap it to the FeedCol width).
            maxWidth: userResized ? 'none' : '100%',
            maxHeight: userResized ? undefined : `${maxHeight}px`,
            aspectRatio: dimensionsKnown ? `${naturalWidth} / ${naturalHeight}` : undefined,
            objectFit: userResized ? 'contain' : 'cover',
            borderRadius: '4px',
            cursor: isMobile ? 'auto' : 'ew-resize',
            userSelect: 'none',
            touchAction: isMobile ? 'auto' : 'none',
            display: 'block'
        };

        if (isImg) {
            return (
                <div ref={wrapperRef} style={{ position: 'relative', display: 'inline-block', maxWidth: mediaStyle.maxWidth, verticalAlign: 'top' }}>
                    <img
                        src={resolved}
                        alt="(inline media)"
                        draggable={false}
                        style={mediaStyle}
                        onLoad={(e) => {
                            if (!mountedRef.current) return;
                            setNaturalWidth(e.currentTarget.naturalWidth);
                            setNaturalHeight(e.currentTarget.naturalHeight);
                        }}
                        {...resizeHandlers}
                    />
                </div>
            );
        }

        if (isStreamDomain || isHlsExt) {
            let videoUid = null;
            const match = u.pathname.match(/^\/?([^/]+)/);
            videoUid = match ? match[1] : null;
            if (!videoUid) {
                return <div style={{ padding: '1rem', background: '#222', borderRadius: '4px', color: '#fff' }}>Invalid video URL</div>;
            }

            return (
                <div
                    ref={wrapperRef}
                    style={{
                        position: 'relative',
                        width: naturalWidth ? `${currentWidth}px` : `${MAX_INITIAL_WIDTH}px`,
                        maxWidth: '100%',
                        aspectRatio: naturalWidth && naturalHeight ? `${naturalWidth} / ${naturalHeight}` : '16 / 9',
                        overflow: 'hidden',
                        borderRadius: '4px',
                    }}
                >
                    {!isMobile && (
                        <>
                            <div style={{ position: 'absolute', top: 0, left: 0, width: '12px', height: '100%', cursor: 'ew-resize', zIndex: 20, userSelect: 'none', touchAction: 'none' }} {...resizeHandlers} />
                            <div style={{ position: 'absolute', top: 0, right: 0, width: '12px', height: '100%', cursor: 'ew-resize', zIndex: 20, userSelect: 'none', touchAction: 'none' }} {...resizeHandlers} />
                        </>
                    )}
                    {(isProcessing || loadFailed) && (
                        <div style={{
                            position: 'absolute', top: 0, left: 0, right: 0, bottom: 0,
                            display: 'flex', alignItems: 'center', justifyContent: 'center',
                            background: 'rgba(0,0,0,0.7)', color: '#fff', zIndex: 10,
                            fontSize: '0.9rem', pointerEvents: 'none'
                        }}>
                            {loadFailed ? 'Video failed to load' : 'Video is still processing...'}
                        </div>
                    )}
                    <video
                        ref={videoRef}
                        controls
                        controlsList="nodownload nofullscreen noremoteplayback"
                        disablePictureInPicture
                        crossOrigin="anonymous"
                        autoPlay={autoPlay}
                        muted={autoPlay}
                        loop={autoPlay}
                        style={{ width: '100%', height: '100%', backgroundColor: '#000', display: 'block' }}
                        onLoadedMetadata={(e) => {
                            if (!mountedRef.current) return;
                            setNaturalWidth(e.currentTarget.videoWidth);
                            setNaturalHeight(e.currentTarget.videoHeight);
                        }}
                        onCanPlay={() => { setIsProcessing(false); setLoadFailed(false); }}
                        preload={autoPlay ? "auto" : "none"}
                    >
                        Your browser does not support HLS video playback.
                    </video>
                </div>
            );
        }

        if (isVid) {
            const src = p.endsWith('.gifv') ? resolved.slice(0, -5) + '.mp4' : resolved;
            return (
                <div
                    ref={wrapperRef}
                    style={{
                        position: 'relative',
                        width: naturalWidth ? `${currentWidth}px` : 'auto',
                        maxWidth: '100%',
                        aspectRatio: naturalWidth && naturalHeight ? `${naturalWidth} / ${naturalHeight}` : undefined,
                        overflow: 'hidden',
                        borderRadius: '4px',
                    }}
                >
                    {!isMobile && (
                        <>
                            <div style={{ position: 'absolute', top: 0, left: 0, width: '12px', height: '100%', cursor: 'ew-resize', zIndex: 20, userSelect: 'none', touchAction: 'none' }} {...resizeHandlers} />
                            <div style={{ position: 'absolute', top: 0, right: 0, width: '12px', height: '100%', cursor: 'ew-resize', zIndex: 20, userSelect: 'none', touchAction: 'none' }} {...resizeHandlers} />
                        </>
                    )}
                    <video
                        src={src}
                        controls
                        controlsList="nodownload nofullscreen noremoteplayback"
                        disablePictureInPicture
                        autoPlay={autoPlay}
                        loop={autoPlay}
                        muted={autoPlay}
                        preload={autoPlay ? "auto" : "metadata"}
                        onLoadedMetadata={(e) => {
                            if (!mountedRef.current) return;
                            setNaturalWidth(e.currentTarget.videoWidth);
                            setNaturalHeight(e.currentTarget.videoHeight);
                        }}
                        style={{ width: '100%', height: '100%', display: 'block' }}
                    />
                </div>
            );
        }

        return <StyledLink href={url} target="_blank" rel="noopener noreferrer">{url}</StyledLink>;
    } catch (_) { }

    return <>{linkifyText(url)}</>;
}

export default function InlineMedia(props) {
    // Structurally unsafe URLs (non-http scheme, embedded credentials, control
    // characters) never render; everything else loads directly.
    if (props.url) {
        const classification = classifyMediaUrl(props.url);
        if (!classification.ok) {
            console.debug('[MediaPolicy] inline rejected', {
                reason: classification.reason,
            });
            return null;
        }
    }
    return <InlineMediaBody {...props} />;
}
