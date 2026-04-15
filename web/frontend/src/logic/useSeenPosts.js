import { useRef, useEffect, useCallback } from "react";
import Storage from "../utils/Storage";
import { signPlainPayload } from "../utils/signPlain";

const DWELL_MS = 3000;
const GLANCE_MS = 150;
const GLANCE_COUNT = 2;
const MAX_BUFFER = 100;
const POST_ID_RE = /^[0-9a-f]{64}$/;
const VALID_REASONS = new Set(["open", "dwell", "glance", "vote", "reply", "view"]);
const _LOG = (...a) => console.log("%c[seen]", "color:#0af;font-weight:bold", ...a);

const _SS_KEY = "_seenReported";
const _SS_CAP = 2000;
const _SAVE_DEBOUNCE_MS = 1000;
const _SB_KEY = "_seenPending";
const _SB_CAP = 500;
const _BUFFER_SAVE_DEBOUNCE_MS = 500;

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

function _loadPendingBuffer() {
    try {
        const raw = sessionStorage.getItem(_SB_KEY);
        if (!raw) return [];
        const arr = JSON.parse(raw);
        if (!Array.isArray(arr)) return [];
        const entries = [];
        for (const item of arr) {
            if (!item || typeof item !== "object") continue;
            const id = _normalizeId(item.id);
            const reason = VALID_REASONS.has(item.reason) ? item.reason : "view";
            if (id) entries.push({ id, reason });
        }
        return entries.slice(0, _SB_CAP);
    } catch (e) {
        _LOG("PENDING load failed:", e.message);
        return [];
    }
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

let _seenBuffer = _loadPendingBuffer();
let _reportedSet = _loadReportedSet();
let _saveTimer = null;
let _bufferSaveTimer = null;
let _drainLock = false;
let _listenerCount = 0;
let _visibilityHandler = null;
let _pageHideHandler = null;
let _flushInterval = null;
const FLUSH_INTERVAL_MS = 3_000;

function _savePendingBufferNow() {
    try {
        const entries = _seenBuffer.slice(0, _SB_CAP);
        sessionStorage.setItem(_SB_KEY, JSON.stringify(entries));
    } catch (e) {
        _LOG("PENDING save failed:", e.message);
    }
}

function _schedulePendingBufferSave() {
    if (_bufferSaveTimer) return;
    _bufferSaveTimer = setTimeout(() => {
        _bufferSaveTimer = null;
        _savePendingBufferNow();
    }, _BUFFER_SAVE_DEBOUNCE_MS);
}

function _flushPendingBufferSave() {
    if (_bufferSaveTimer) {
        clearTimeout(_bufferSaveTimer);
        _bufferSaveTimer = null;
    }
    _savePendingBufferNow();
}

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

function _ensureFlushInterval() {
    if (_flushInterval) return;
    _flushInterval = setInterval(() => {
        if (_seenBuffer.length > 0) {
            _LOG(`TIMER  ${_seenBuffer.length} buffered → flush`);
            void flushSeenBeacon();
        }
    }, FLUSH_INTERVAL_MS);
}

if (_seenBuffer.length > 0) {
    _ensureFlushInterval();
}

function markSeen(pid, reason) {
    const addr = _getAddress();
    if (!addr || addr === "guest") {
        _LOG("SKIP  no address, seen not queued");
        return;
    }
    const id = _normalizeId(pid);
    if (!id || _reportedSet.has(id)) return;
    _reportedSet.add(id);
    _scheduleReportedSetSave();
    const finalReason = VALID_REASONS.has(reason) ? reason : "view";
    _seenBuffer.push({ id, reason: finalReason });
    if (_seenBuffer.length > _SB_CAP) {
        _seenBuffer = _seenBuffer.slice(-_SB_CAP);
    }
    _schedulePendingBufferSave();
    _LOG(`MARK  ${id.slice(0, 12)}…  reason=${finalReason}  buffer=${_seenBuffer.length}/${MAX_BUFFER}  persisted=${_reportedSet.size}`);
    _ensureFlushInterval();
    if (_seenBuffer.length >= MAX_BUFFER) {
        void flushSeenBeacon();
    }
}

async function _drainSeenBatch() {
    if (_drainLock || _seenBuffer.length === 0) return null;
    const addr = _getAddress();
    if (!addr || addr === "guest") return null;
    _drainLock = true;
    const entries = _seenBuffer.splice(0, MAX_BUFFER);
    _schedulePendingBufferSave();
    _LOG(`DRAIN  ${entries.length} entries`);
    try {
        const sig = await signPlainPayload((ts, n) => `seen_posts:${addr}:${ts}:${n}`);
        return { address: addr, entries, sig };
    } catch (e) {
        _seenBuffer = entries.concat(_seenBuffer);
        _schedulePendingBufferSave();
        _LOG("DRAIN  sign failed, restored to buffer:", e.message);
        return null;
    } finally {
        _drainLock = false;
    }
}

function _restoreSeenBatch(batch) {
    if (!batch || !Array.isArray(batch.entries) || batch.entries.length === 0) return;
    const existing = new Set(_seenBuffer.map((entry) => entry.id));
    const restored = batch.entries.filter((entry) => !existing.has(entry.id));
    if (restored.length) {
        _seenBuffer = restored.concat(_seenBuffer);
        _schedulePendingBufferSave();
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
    const batch = await _drainSeenBatch();
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
            _restoreSeenBatch(batch);
        }
    } catch (e) {
        _LOG("BEACON  error:", e.message);
        _restoreSeenBatch(batch);
    }
}

export function useSeenPosts() {
    const observerRef = useRef(null);
    const dwellTimersRef = useRef(new Map());
    const entryTimesRef = useRef(new Map());
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
                    _flushPendingBufferSave();
                    for (const timer of dwellTimersRef.current.values()) clearTimeout(timer);
                    dwellTimersRef.current.clear();
                    entryTimesRef.current.clear();
                    void flushSeenBeacon();
                }
            };
            document.addEventListener("visibilitychange", _visibilityHandler);
        }
        if (!_pageHideHandler) {
            _pageHideHandler = () => {
                _flushReportedSetSave();
                _flushPendingBufferSave();
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
            const marginTop = Math.round(vh * 0.08);
            const marginBottom = Math.round(vh * 0.15);
            const rootMargin = `-${marginTop}px 0px -${marginBottom}px 0px`;

            _LOG(`OBSERVER  vh=${vh}  rootMargin="${rootMargin}"  reportedSet=${_reportedSet.size}  observed=${observedElementsRef.current.size}`);

            if (observerRef.current) {
                observerRef.current.disconnect();
            }
            observerRef.current = new IntersectionObserver(
                (entries) => {
                    if (!visibleRef.current) return;
                    const now = Date.now();
                    for (const entry of entries) {
                        const el = entry.target;
                        const pid = el.dataset.postId;
                        if (!pid) continue;
                        const id = _normalizeId(pid);
                        if (!id) {
                            _LOG(`SKIP  pid=${String(pid).slice(0, 12)}…  invalid id`);
                            continue;
                        }
                        if (_reportedSet.has(id)) {
                            _LOG(`DEDUP  ${id.slice(0, 12)}…  already in reportedSet → skip`);
                            const dwell = dwellTimersRef.current.get(id);
                            if (dwell) clearTimeout(dwell);
                            dwellTimersRef.current.delete(id);
                            entryTimesRef.current.delete(id);
                            glanceCountsRef.current.delete(id);
                            continue;
                        }

                        const ratio = entry.intersectionRatio || 0;
                        const glanceVisible = entry.isIntersecting && ratio >= 0.3;
                        const dwellVisible = entry.isIntersecting && ratio >= 0.4;
                        _LOG(`IO  ${id.slice(0, 12)}…  intersecting=${entry.isIntersecting}  ratio=${ratio.toFixed(3)}  glance=${glanceVisible}  dwell=${dwellVisible}  hasDwellTimer=${dwellTimersRef.current.has(id)}`);

                        if (glanceVisible) {
                            if (!entryTimesRef.current.has(id)) {
                                entryTimesRef.current.set(id, now);
                            }
                        } else {
                            const enterTime = entryTimesRef.current.get(id);
                            entryTimesRef.current.delete(id);
                            if (enterTime && (now - enterTime) >= GLANCE_MS) {
                                const nextCount = (glanceCountsRef.current.get(id) || 0) + 1;
                                glanceCountsRef.current.set(id, nextCount);
                                _LOG(`GLANCE ${id.slice(0, 12)}…  count=${nextCount}/${GLANCE_COUNT}  visible=${now - enterTime}ms`);
                                if (glanceCountsRef.current.size > 5000) {
                                    glanceCountsRef.current.clear();
                                }
                                if (nextCount >= GLANCE_COUNT) {
                                    glanceCountsRef.current.delete(id);
                                    const pendingDwell = dwellTimersRef.current.get(id);
                                    if (pendingDwell) clearTimeout(pendingDwell);
                                    dwellTimersRef.current.delete(id);
                                    markSeen(id, "glance");
                                }
                            }
                        }

                        if (dwellVisible) {
                            if (!dwellTimersRef.current.get(id)) {
                                const timer = setTimeout(() => {
                                    dwellTimersRef.current.delete(id);
                                    _LOG(`DWELL  ${id.slice(0, 12)}…  ${DWELL_MS}ms elapsed → mark`);
                                    markSeen(id, "dwell");
                                }, DWELL_MS);
                                dwellTimersRef.current.set(id, timer);
                            }
                        } else {
                            const dwell = dwellTimersRef.current.get(id);
                            if (dwell) clearTimeout(dwell);
                            dwellTimersRef.current.delete(id);
                        }
                    }
                },
                {
                    threshold: [0, 0.3, 0.4],
                    rootMargin,
                }
            );
            for (const el of observedElementsRef.current) {
                observerRef.current.observe(el);
            }
        };

        let resizeTimer = null;
        const handleResize = () => {
            if (resizeTimer) clearTimeout(resizeTimer);
            resizeTimer = setTimeout(() => { resizeTimer = null; createObserver(); }, 500);
        };
        createObserver();
        window.addEventListener("resize", handleResize);
        return () => {
            if (resizeTimer) clearTimeout(resizeTimer);
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
            const pid = el.dataset?.postId;
            const id = _normalizeId(pid);
            if (id) {
                const dwell = dwellTimersRef.current.get(id);
                if (dwell) clearTimeout(dwell);
                dwellTimersRef.current.delete(id);
                entryTimesRef.current.delete(id);
                glanceCountsRef.current.delete(id);
            }
        }
    }, []);

    return { observePost, unobservePost };
}

export default useSeenPosts;
