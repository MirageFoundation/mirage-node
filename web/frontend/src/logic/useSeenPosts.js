import { useRef, useEffect, useCallback } from "react";
import Storage from "../utils/Storage";
import { signPlainPayload } from "../utils/signPlain";

const DWELL_MS = 3000;
const GLANCE_MS = 500;
const GLANCE_COUNT = 2;
const MAX_BUFFER = 100;
const POST_ID_RE = /^[0-9a-f]{64}$/;
const VALID_REASONS = new Set(["open", "dwell", "glance", "vote", "reply", "view"]);
const _LOG = (...a) => console.log("%c[seen]", "color:#0af;font-weight:bold", ...a);

const _SS_KEY = "_seenReported";
const _SS_CAP = 2000;
const _SAVE_DEBOUNCE_MS = 1000;

function _loadReportedSet() {
    try {
        const raw = sessionStorage.getItem(_SS_KEY);
        if (raw) {
            const arr = JSON.parse(raw);
            if (Array.isArray(arr) && arr.length <= _SS_CAP) return new Set(arr);
        }
    } catch (_) { /* noop */ }
    return new Set();
}

function _saveReportedSetNow() {
    try {
        if (_reportedSet.size > _SS_CAP) {
            _reportedSet.clear();
            sessionStorage.removeItem(_SS_KEY);
            return;
        }
        sessionStorage.setItem(_SS_KEY, JSON.stringify([..._reportedSet]));
    } catch (_) { /* noop */ }
}

function _scheduleReportedSetSave() {
    if (_saveTimer) return;
    _saveTimer = setTimeout(() => {
        _saveTimer = null;
        _saveReportedSetNow();
    }, _SAVE_DEBOUNCE_MS);
}

function _flushReportedSetSave() {
    if (_saveTimer) {
        clearTimeout(_saveTimer);
        _saveTimer = null;
    }
    _saveReportedSetNow();
}

let _seenBuffer = [];
let _reportedSet = _loadReportedSet();
let _saveTimer = null;
let _drainLock = false;
let _listenerCount = 0;
let _visibilityHandler = null;
let _pageHideHandler = null;
let _flushInterval = null;
const FLUSH_INTERVAL_MS = 10_000;

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

function _ensureFlushInterval() {
    if (_flushInterval) return;
    _flushInterval = setInterval(() => {
        if (_seenBuffer.length > 0) {
            _LOG(`TIMER  ${_seenBuffer.length} buffered → flush`);
            void flushSeenBeacon();
        }
    }, FLUSH_INTERVAL_MS);
}

function markSeen(pid, reason) {
    const addr = _getAddress();
    if (!addr || addr === "guest") return;
    const id = _normalizeId(pid);
    if (!id || _reportedSet.has(id)) return;
    _reportedSet.add(id);
    _scheduleReportedSetSave();
    const finalReason = VALID_REASONS.has(reason) ? reason : "view";
    _seenBuffer.push({ id, reason: finalReason });
    _LOG(`MARK  ${id.slice(0, 12)}…  reason=${finalReason}  buffer=${_seenBuffer.length}/${MAX_BUFFER}  persisted=${_reportedSet.size}`);
    _ensureFlushInterval();
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
    _LOG(`DRAIN  ${entries.length} entries → piggyback`);
    try {
        const sig = await signPlainPayload((ts, n) => `seen_posts:${addr}:${ts}:${n}`);
        return { address: addr, entries, sig, encoded: _encodeEntries(entries) };
    } catch (_) {
        _seenBuffer = entries.concat(_seenBuffer);
        _LOG("DRAIN  sign failed, restored to buffer");
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
        _LOG(`RESTORE  ${restored.length} entries back to buffer (total=${_seenBuffer.length})`);
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
        _LOG(`BEACON  ${batch.entries.length} posts → ${ok ? "sent ✓" : "FAILED ✗"}`);
        if (!ok) {
            restoreSeenBatch(batch);
        }
    } catch (e) {
        _LOG("BEACON  error:", e.message);
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
                    _flushReportedSetSave();
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
            _pageHideHandler = () => {
                _flushReportedSetSave();
                void flushSeenBeacon();
            };
            window.addEventListener("pagehide", _pageHideHandler);
        }
        _ensureFlushInterval();
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
                                    _LOG(`DWELL  ${id.slice(0, 12)}…  ${DWELL_MS}ms elapsed → mark`);
                                    markSeen(id, "dwell");
                                }, DWELL_MS);
                                dwellTimersRef.current.set(id, timer);
                            }
                            if (!glanceTimersRef.current.get(id)) {
                                const timer = setTimeout(() => {
                                    glanceTimersRef.current.delete(id);
                                    const nextCount = (glanceCountsRef.current.get(id) || 0) + 1;
                                    glanceCountsRef.current.set(id, nextCount);
                                    _LOG(`GLANCE ${id.slice(0, 12)}…  count=${nextCount}/${GLANCE_COUNT}`);
                                    if (glanceCountsRef.current.size > 5000) {
                                        glanceCountsRef.current.clear();
                                    }
                                    if (nextCount >= GLANCE_COUNT) {
                                        glanceCountsRef.current.delete(id);
                                        const pendingDwell = dwellTimersRef.current.get(id);
                                        if (pendingDwell) {
                                            clearTimeout(pendingDwell);
                                            dwellTimersRef.current.delete(id);
                                        }
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
