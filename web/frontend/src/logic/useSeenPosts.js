import { useRef, useEffect, useCallback } from "react";
import Storage from "../utils/Storage";
import { signPlainPayload } from "../utils/signPlain";

const DWELL_MS = 5000;
const GLANCE_MS = 400;
const GLANCE_COUNT = 3;
const MAX_BUFFER = 100;
const POST_ID_RE = /^[0-9a-f]{64}$/;
const VALID_REASONS = new Set(["open", "dwell", "glance", "vote", "reply", "view"]);

let _seenBuffer = [];
let _reportedSet = new Set();
let _drainLock = false;
let _listenerCount = 0;
let _visibilityHandler = null;
let _pageHideHandler = null;

function _getAddress() {
    try {
        const raw = Storage.load("publicKey", "");
        return typeof raw === "string" ? raw.trim().toLowerCase() : "";
    } catch (_) {
        return "";
    }
}

function _normalizeId(pid) {
    const raw = String(pid || "").trim().toLowerCase();
    return POST_ID_RE.test(raw) ? raw : "";
}

function _getApiBase() {
    try {
        let base = '/api';
        const env = (typeof process !== 'undefined' && process.env && process.env.REACT_APP_API_BASE)
            ? process.env.REACT_APP_API_BASE
            : '';
        if (env) {
            base = String(env).trim() || '/api';
        }
        if (!/\/?api\/?$/.test(base)) {
            base = base.replace(/\/$/, '') + '/api';
        }
        return base.replace(/\/$/, '');
    } catch (_) {
        return '/api';
    }
}

function _buildUrl(path) {
    const base = _getApiBase();
    const p = String(path || '').replace(/^\//, '');
    if (base.startsWith('http://') || base.startsWith('https://')) {
        return new URL(base + '/' + p).toString();
    }
    return new URL(base + '/' + p, window.location.origin).toString();
}

function _encodeEntries(entries) {
    return entries.map((entry) => `${entry.id}:${entry.reason}`).join(",");
}

function markSeen(pid, reason) {
    const addr = _getAddress();
    if (!addr || addr === "guest") return;
    const id = _normalizeId(pid);
    if (!id || _reportedSet.has(id)) return;
    _reportedSet.add(id);
    const finalReason = VALID_REASONS.has(reason) ? reason : "view";
    _seenBuffer.push({ id, reason: finalReason });
    if (_seenBuffer.length >= MAX_BUFFER) {
        void flushSeenBeacon();
    }
}

export async function drainSeenBatch() {
    if (_drainLock || _seenBuffer.length === 0) return null;
    const addr = _getAddress();
    if (!addr || addr === "guest") return null;
    _drainLock = true;
    const entries = _seenBuffer.splice(0, MAX_BUFFER);
    try {
        const sig = await signPlainPayload((ts, n) => `seen_posts:${addr}:${ts}:${n}`);
        return { address: addr, entries, sig, encoded: _encodeEntries(entries) };
    } catch (_) {
        _seenBuffer = entries.concat(_seenBuffer);
        return null;
    } finally {
        _drainLock = false;
    }
}

export function restoreSeenBatch(batch) {
    if (!batch || !Array.isArray(batch.entries) || batch.entries.length === 0) return;
    const existing = new Set(_seenBuffer.map((entry) => entry.id));
    const restored = batch.entries.filter((entry) => !existing.has(entry.id));
    if (restored.length) {
        _seenBuffer = restored.concat(_seenBuffer);
    }
}

export function markPostOpened(pid) {
    markSeen(pid, "open");
}

export function markPostVoted(pid) {
    markSeen(pid, "vote");
}

export function markPostReplied(pid) {
    markSeen(pid, "reply");
}

async function flushSeenBeacon() {
    const batch = await drainSeenBatch();
    if (!batch) return;
    try {
        const payload = JSON.stringify({
            address: batch.address,
            posts: batch.entries,
            ...batch.sig,
        });
        const ok = navigator.sendBeacon(
            _buildUrl("seen_posts"),
            new Blob([payload], { type: "application/json" }),
        );
        if (!ok) {
            restoreSeenBatch(batch);
        }
    } catch (_) {
        restoreSeenBatch(batch);
    }
}

export function useSeenPosts() {
    const observerRef = useRef(null);
    const dwellTimersRef = useRef(new Map());
    const glanceTimersRef = useRef(new Map());
    const glanceCountsRef = useRef(new Map());
    const observedElementsRef = useRef(new Set());
    const visibleRef = useRef(true);

    useEffect(() => {
        _listenerCount += 1;
        if (!_visibilityHandler) {
            _visibilityHandler = () => {
                visibleRef.current = document.visibilityState === "visible";
                if (!visibleRef.current) {
                    for (const timer of dwellTimersRef.current.values()) clearTimeout(timer);
                    for (const timer of glanceTimersRef.current.values()) clearTimeout(timer);
                    dwellTimersRef.current.clear();
                    glanceTimersRef.current.clear();
                    void flushSeenBeacon();
                }
            };
            document.addEventListener("visibilitychange", _visibilityHandler);
        }
        if (!_pageHideHandler) {
            _pageHideHandler = () => { void flushSeenBeacon(); };
            window.addEventListener("pagehide", _pageHideHandler);
        }
        return () => {
            _listenerCount -= 1;
            if (_listenerCount <= 0) {
                if (_visibilityHandler) {
                    document.removeEventListener("visibilitychange", _visibilityHandler);
                    _visibilityHandler = null;
                }
                if (_pageHideHandler) {
                    window.removeEventListener("pagehide", _pageHideHandler);
                    _pageHideHandler = null;
                }
            }
        };
    }, []);

    useEffect(() => {
        const createObserver = () => {
            const vh = window.innerHeight || document.documentElement.clientHeight;
            const marginTop = Math.round(vh * 0.3);
            const marginBottom = Math.round(vh * 0.3);
            const rootMargin = `-${marginTop}px 0px -${marginBottom}px 0px`;

            if (observerRef.current) {
                observerRef.current.disconnect();
            }
            observerRef.current = new IntersectionObserver(
                (entries) => {
                    if (!visibleRef.current) return;
                    for (const entry of entries) {
                        const el = entry.target;
                        const pid = el.dataset.postId;
                        if (!pid) continue;
                        const id = _normalizeId(pid);
                        if (!id || _reportedSet.has(id)) {
                            const dwell = dwellTimersRef.current.get(id);
                            if (dwell) clearTimeout(dwell);
                            const glance = glanceTimersRef.current.get(id);
                            if (glance) clearTimeout(glance);
                            dwellTimersRef.current.delete(id);
                            glanceTimersRef.current.delete(id);
                            glanceCountsRef.current.delete(id);
                            continue;
                        }

                        if (entry.isIntersecting) {
                            if (!dwellTimersRef.current.get(id)) {
                                const timer = setTimeout(() => {
                                    dwellTimersRef.current.delete(id);
                                    markSeen(id, "dwell");
                                }, DWELL_MS);
                                dwellTimersRef.current.set(id, timer);
                            }
                            if (!glanceTimersRef.current.get(id)) {
                                const timer = setTimeout(() => {
                                    glanceTimersRef.current.delete(id);
                                    const nextCount = (glanceCountsRef.current.get(id) || 0) + 1;
                                    glanceCountsRef.current.set(id, nextCount);
                                    if (glanceCountsRef.current.size > 5000) {
                                        glanceCountsRef.current.clear();
                                    }
                                    if (nextCount >= GLANCE_COUNT) {
                                        glanceCountsRef.current.delete(id);
                                        markSeen(id, "glance");
                                    }
                                }, GLANCE_MS);
                                glanceTimersRef.current.set(id, timer);
                            }
                        } else {
                            const dwell = dwellTimersRef.current.get(id);
                            if (dwell) clearTimeout(dwell);
                            dwellTimersRef.current.delete(id);
                            const glance = glanceTimersRef.current.get(id);
                            if (glance) clearTimeout(glance);
                            glanceTimersRef.current.delete(id);
                        }
                    }
                },
                {
                    threshold: [0.4, 0.5],
                    rootMargin,
                }
            );
            for (const el of observedElementsRef.current) {
                observerRef.current.observe(el);
            }
        };

        const handleResize = () => createObserver();
        createObserver();
        window.addEventListener("resize", handleResize);
        return () => {
            window.removeEventListener("resize", handleResize);
            if (observerRef.current) {
                observerRef.current.disconnect();
                observerRef.current = null;
            }
        };
    }, []);

    const observePost = useCallback((el) => {
        if (el) {
            observedElementsRef.current.add(el);
            if (observerRef.current) {
                observerRef.current.observe(el);
            }
        }
    }, []);

    const unobservePost = useCallback((el) => {
        if (el) {
            observedElementsRef.current.delete(el);
            if (observerRef.current) {
                observerRef.current.unobserve(el);
            }
        }
    }, []);

    return { observePost, unobservePost };
}

export default useSeenPosts;
