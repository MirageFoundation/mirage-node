import React from "react";
import { useState, useEffect } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import * as tx from "../utils/tx.js";
import Api from "../utils/api";
import Storage from "../utils/Storage";
import { formatError } from "../utils/errorMessages";
import { requireAccount } from "../utils/openBrowsing";
import { getVideoThumbnailUrl, isLikelyImageUrl, isLikelyVideoUrl } from "../utils/media";
import { updateNotification } from "../utils/notifications";
export const TAG_OPTIONS = [{
    value: '',
    label: 'No tag (safe)'
}, {
    value: 'sensitive',
    label: 'Sensitive (blur content)'
}, {
    value: 'adult',
    label: 'Adult'
}, {
    value: 'violence',
    label: 'Violence'
}, {
    value: 'gore',
    label: 'Gore'
}, {
    value: 'death',
    label: 'Death'
}];
export const TAG_OPTIONS_ENABLED = TAG_OPTIONS.filter(t => t.value);
export function useCreatePost({
    state,
    setPosts,
    updatePost
}) {
    let navigate = useNavigate();
    const location = useLocation();
    const locationState = location?.state;
    const locationSearch = location?.search;
    const params = React.useMemo(() => new URLSearchParams(locationSearch || ''), [locationSearch]);
    const isEditMode = params.get('edit') === 'true' && !!params.get('post_id');
    const overrideId = params.get('post_id') || '';
    const getCurrentTopic = () => {
        try {
            const referrer = document.referrer || '';
            const topicMatch = referrer.match(/\/t\/([^/?]+)/);
            if (topicMatch && topicMatch[1] && topicMatch[1] !== 'all') {
                return topicMatch[1];
            }
        } catch (_) { }
        return null;
    };
    const getPreferredTopic = React.useCallback(() => {
        try {
            const st = locationState && locationState.fromTopic;
            if (st && st !== 'all') {
                return String(st).replace(/[^a-zA-Z0-9]/g, '').toLowerCase();
            }
        } catch (_) { }
        try {
            const params = new URLSearchParams(locationSearch || '');
            const qp = params.get('topic');
            if (qp && qp !== 'all') {
                return String(qp).replace(/[^a-zA-Z0-9]/g, '').toLowerCase();
            }
        } catch (_) { }
        const ref = getCurrentTopic();
        if (ref && ref !== 'all') {
            return String(ref).replace(/[^a-zA-Z0-9]/g, '').toLowerCase();
        }
        return '';
    }, [locationState, locationSearch]);
    const preferredTopic = React.useMemo(() => getPreferredTopic(), [getPreferredTopic]);
    const [topicValue, setTopicValue] = useState(() => preferredTopic || '');
    const [titleValue, setTitleValue] = useState('');
    const [contentValue, setContentValue] = useState('');
    const [submitError, setSubmitError] = useState('');
    const errorSetTimeRef = React.useRef(null);
    const errorClearTimeoutRef = React.useRef(null);
    const [isSubmitting, setIsSubmitting] = useState(false);
    const [submitStartTime, setSubmitStartTime] = useState(null);
    const [, setElapsedTime] = useState(0);
    const [submitStatus, setSubmitStatus] = useState('idle'); // idle, solving, submitting, verifying
    const [configUpdateTrigger, setConfigUpdateTrigger] = useState(0);
    const [editorUpload, setEditorUpload] = useState(null);
    /* `globalDragging` powers the page-wide drop overlay in the onyx,
     * bluemoon, and oldreddit themes. The default theme deliberately
     * doesn't read it — it ships with a single inline drop panel as
     * the only drop target — but we keep the state here so the shared
     * hook stays drop-in compatible across all themes. */
    const [globalDragging, setGlobalDragging] = useState(false);
    const [attachedMedia, setAttachedMedia] = useState([]); // [{type: 'image'|'video', url: string}]
    const MAX_MEDIA = 10;
    const [isUploading, setIsUploading] = useState(false);
    const [uploadProgress, setUploadProgress] = useState(null);
    const [thumbsLoading, setThumbsLoading] = useState(new Set()); // Set<string> of URLs still loading their thumbnail
    const [tagValue, setTagValue] = useState('');
    const [tagEnabled, setTagEnabled] = useState(false);
    const [tagManuallySet, setTagManuallySet] = useState(false);
    const titleInputRef = React.useRef(null);
    const contentEditorRef = React.useRef(null);
    const mountedRef = React.useRef(true);

    // Track component mount status
    React.useEffect(() => {
        mountedRef.current = true;
        return () => {
            mountedRef.current = false;
        };
    }, []);
    useEffect(() => {
        if (!isEditMode || !overrideId) return;
        const load = async () => {
            try {
                const viewerAddress = Storage.load('publicKey', '');
                const data = await Api.get('get_comments', {
                    post_id: overrideId,
                    address: viewerAddress,
                    lens: 'effective',
                    scope: 'current',
                });
                if (data && data.root) {
                    setTopicValue(data.root.topic || '');
                    setTitleValue(data.root.title || '');
                    const content = data.root.content || '';
                    const tagLower = (data.root.tag || '').toLowerCase();
                    setTagValue(tagLower);
                    setTagEnabled(!!tagLower);
                    setTagManuallySet(!!tagLower);
                    // v1.12.0+: Load from dedicated media array if available
                    const mediaArr = Array.isArray(data.root.media) ? data.root.media : [];
                    if (mediaArr.length > 0) {
                        const items = mediaArr.slice(0, MAX_MEDIA).map(url => {
                            const type = isLikelyVideoUrl(url) ? 'video' : 'image';
                            return {
                                type,
                                url
                            };
                        });
                        console.debug('[CreatePostView] edit preload media[]:', items.map(m => `${m.type}:${m.url}`));
                        setAttachedMedia(items);
                        setThumbsLoading(new Set(items.map(m => m.url)));
                        setContentValue(content);
                    } else {
                        // Legacy: extract first-line media from content
                        const lines = content.split('\n');
                        const firstLine = lines[0]?.trim() || '';
                        if (/^https?:\/\//i.test(firstLine)) {
                            const isImage = isLikelyImageUrl(firstLine);
                            const isVideo = isLikelyVideoUrl(firstLine);
                            if (isImage || isVideo) {
                                setAttachedMedia([{
                                    type: isImage ? 'image' : 'video',
                                    url: firstLine
                                }]);
                                setThumbsLoading(new Set([firstLine]));
                                const restLines = lines.slice(1);
                                while (restLines.length > 0 && restLines[0].trim() === '') {
                                    restLines.shift();
                                }
                                setContentValue(restLines.join('\n'));
                            } else {
                                setContentValue(content);
                            }
                        } else {
                            setContentValue(content);
                        }
                    }
                }
            } catch (e) {
                console.error('[CreatePostView] Failed to preload post for edit:', e);
            }
        };
        load();
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [isEditMode, overrideId]);
    useEffect(() => {
        if ((!topicValue || topicValue === '') && preferredTopic) {
            setTopicValue(preferredTopic);
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [preferredTopic]);

    // Auto-populate the content tag when the composer opens with a pre-filled
    // topic (via referrer like `/t/gore` → "Create Post", URL `?topic=foo`,
    // or nav state `fromTopic`). `handleTopicChange` already covers this for
    // user-picked topics via `meta.dominant_tag` from `TopicSelector`, but
    // pre-filled topics never go through that path — `topicValue` lands in
    // state directly without any meta. We do an explicit one-shot lookup so
    // the same auto-apply works regardless of how the topic got there.
    //
    // Bails in edit mode (the post-loader sets the tag from the post itself
    // and marks it as manually set) and respects `tagManuallySet` so we
    // don't trample explicit user / preload intent. Override `allowed_tags`
    // with the full set since the user's display preferences shouldn't hide
    // the tag of the topic they're actively posting in.
    useEffect(() => {
        if (isEditMode) return;
        if (!topicValue) return;
        if (tagManuallySet) return;
        let cancelled = false;
        (async () => {
            try {
                // Dominant-tag auto-apply used retired search_topics. Communities
                // list has no tag stats, so leave the tag unset unless the user
                // (or TopicSelector) sets it explicitly.
                void topicValue;
            } catch (_) { /* noop */ }
        })();
        return () => { cancelled = true; };
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);
    useEffect(() => {
        const handleStorageChange = e => {
            if (e.key === 'chainConfig' || e.key === 'user_balance' || e.key === 'user_level') {
                setConfigUpdateTrigger(prev => prev + 1);
            }
        };
        const handleConfigUpdate = () => {
            setConfigUpdateTrigger(prev => prev + 1);
        };
        window.addEventListener('storage', handleStorageChange);
        window.addEventListener('chainConfigUpdated', handleConfigUpdate);
        window.addEventListener('userStatusUpdated', handleConfigUpdate);
        return () => {
            window.removeEventListener('storage', handleStorageChange);
            window.removeEventListener('chainConfigUpdated', handleConfigUpdate);
            window.removeEventListener('userStatusUpdated', handleConfigUpdate);
        };
    }, []);
    useEffect(() => {
        // Always refresh on mount of the composer so tier-aware limits
        // (max_title_length / max_content_length) are not stuck on a stale
        // cache. If the cached config is also missing or has no tiers, this
        // ensures we hydrate before the user starts typing.
        let cancelled = false;
        const refresh = () => {
            Api.get('get_chain_config', undefined).then(cfg => {
                if (cancelled || !cfg) return;
                try { tx.cacheChainConfig(cfg); } catch (_) { }
            }).catch(() => { });
        };
        let tiersOk = false;
        try {
            const raw = localStorage.getItem('chainConfig');
            const parsed = raw ? JSON.parse(raw) : null;
            tiersOk = !!(parsed && Array.isArray(parsed.tiers) && parsed.tiers.length > 0
                && parseInt(parsed.tiers[0]?.max_title_length) > 0);
        } catch (_) { tiersOk = false; }
        if (!tiersOk || tx.needsChainConfigRefresh()) {
            refresh();
        }
        return () => { cancelled = true; };
    }, []);

    // eslint-disable-next-line react-hooks/exhaustive-deps
    const limits = React.useMemo(() => {
        void configUpdateTrigger;
        try {
            const chainRaw = localStorage.getItem('chainConfig');
            const chain = JSON.parse(chainRaw || '{}');
            const userLevel = parseInt(Storage.load('user_level', '0'));
            const tiers = chain.tiers || [];
            // Free=0, Subscriber=1, Admin(>=100)=2 — matches LevelToTierIndex.
            const tierIndex = userLevel === 0 ? 0 : userLevel >= 100 ? 2 : 1;
            const isAdmin = userLevel >= 100;
            let tier = tiers[tierIndex] || tiers[tiers.length - 1] || {};
            let maxTitle = parseInt(tier.max_title_length) || 0;
            let maxContent = parseInt(tier.max_content_length) || 0;
            // Sensible fallbacks if chain config hasn't loaded yet.
            if (!maxTitle) maxTitle = 150;
            if (!maxContent) maxContent = 1000;
            return {
                maxTitle,
                maxContent,
                maxTopic: parseInt(chain.max_topic_size) || 50,
                minTopic: parseInt(chain.min_topic_size) || 2,
                willPayFee: userLevel >= 1,
                isAdmin
            };
        } catch (e) {
            console.error('[CreatePostView] Error calculating limits:', e);
            return {
                maxTitle: 150,
                maxContent: 1000,
                maxTopic: 50,
                minTopic: 2,
                willPayFee: false,
                isAdmin: false
            };
        }
    }, [configUpdateTrigger]);
    useEffect(() => {
        return () => {
            if (errorClearTimeoutRef.current) {
                clearTimeout(errorClearTimeoutRef.current);
                errorClearTimeoutRef.current = null;
            }
        };
    }, []);
    useEffect(() => {
        if (!submitStartTime || !isSubmitting) {
            setElapsedTime(0);
            return;
        }
        const interval = setInterval(() => {
            setElapsedTime((Date.now() - submitStartTime) / 1000);
        }, 100);
        return () => clearInterval(interval);
    }, [submitStartTime, isSubmitting]);

    // Window-level Ctrl+V media paste — covers the cases where focus is NOT
    // on the title input or the body textarea (both of which already have
    // their own `onPaste` handlers via `handleTitlePaste` and the
    // `MarkdownEditor`'s internal `handlePaste`). Without this, clicking
    // any chip / button / drop-panel target moves focus away from the
    // text inputs and a subsequent Ctrl+V lands on a non-handler and
    // silently does nothing. Mirrors the whole-page drag/drop behavior on
    // `ContentGrid` so paste-to-upload works from anywhere on the page.
    useEffect(() => {
        const handleWindowPaste = e => {
            try {
                // Skip when an input/textarea/contenteditable owns the
                // event — those have their own handlers and we'd
                // double-upload otherwise.
                const target = e.target;
                const tag = target?.tagName?.toLowerCase();
                if (tag === 'input' || tag === 'textarea') return;
                if (target?.isContentEditable) return;

                if (isSubmitting || isUploading) return;
                if (attachedMedia.length >= MAX_MEDIA) return;
                if (!editorUpload || typeof editorUpload.uploadFile !== 'function') return;

                const cd = e.clipboardData || window.clipboardData;
                if (!cd) return;

                let file = null;
                if (cd.items && cd.items.length) {
                    for (let i = 0; i < cd.items.length; i += 1) {
                        const it = cd.items[i];
                        if (!it || it.kind !== 'file') continue;
                        const f = it.getAsFile && it.getAsFile();
                        if (f && (f.type?.startsWith('image/') || f.type?.startsWith('video/'))) {
                            file = f;
                            break;
                        }
                    }
                }
                if (!file && cd.files && cd.files.length) {
                    for (let i = 0; i < cd.files.length; i += 1) {
                        const f = cd.files[i];
                        if (f && (f.type?.startsWith('image/') || f.type?.startsWith('video/'))) {
                            file = f;
                            break;
                        }
                    }
                }

                if (file) {
                    e.preventDefault();
                    editorUpload.uploadFile(file);
                }
            } catch (_) { /* noop */ }
        };
        window.addEventListener('paste', handleWindowPaste);
        return () => window.removeEventListener('paste', handleWindowPaste);
    }, [isSubmitting, isUploading, attachedMedia.length, editorUpload, MAX_MEDIA]);

    const handleTopicChange = e => {
        let formattedValue = e.target.value.replace(/[^a-zA-Z0-9]/g, '').toLowerCase();
        if (formattedValue.length > limits.maxTopic) {
            formattedValue = formattedValue.slice(0, limits.maxTopic);
        }
        const prevTopic = topicValue;

        // Ignore empty or identical values to avoid clearing when reopening selector
        if (!formattedValue && prevTopic) {
            if (submitError) setSubmitError('');
            return;
        }
        if (formattedValue === prevTopic) {
            if (submitError) setSubmitError('');
            return;
        }
        setTopicValue(formattedValue);

        // Tag follows the new topic deterministically: pick up the topic's
        // dominant tag, or clear the tag entirely if the topic has none.
        // We don't honor `tagManuallySet` here — selecting a different
        // topic is itself a strong signal that the previous tag may no
        // longer apply, and surprise from the rare overwrite is less bad
        // than mismatched content getting posted into the wrong topic.
        const meta = e.meta || {};
        const dominantTag = (meta.dominant_tag || '').toLowerCase();
        if (dominantTag) {
            setTagEnabled(true);
            setTagValue(dominantTag);
        } else {
            setTagEnabled(false);
            setTagValue('');
        }
        // Reset to "auto-applied" so the next topic change can re-apply
        // freely. Manual overrides via `handleTagSelect` still set this
        // back to `true`, but only the mount-time pre-fill effect honors
        // it (to avoid stomping the post-loader's tag in edit mode).
        setTagManuallySet(false);

        if (submitError) setSubmitError('');
    };

    // Count UTF-8 bytes (Go's len() counts bytes, not characters)
    const getByteLength = str => new TextEncoder().encode(str).length;
    const handleTitleChange = e => {
        let value = e.target.value;
        // Truncate by removing characters until byte length is within limit
        while (getByteLength(value) > limits.maxTitle && value.length > 0) {
            value = value.slice(0, -1);
        }
        setTitleValue(value);
        if (submitError) setSubmitError('');
    };
    // Helper: add a media item and mark its URL as loading a thumbnail
    const addMediaItem = (type, url) => {
        setAttachedMedia(prev => {
            if (prev.length >= MAX_MEDIA) return prev;
            return [...prev, {
                type,
                url
            }];
        });
        setThumbsLoading(prev => {
            const n = new Set(prev);
            n.add(url);
            return n;
        });
    };
    const handleTitlePaste = async e => {
        try {
            if (isSubmitting || isUploading) return;
            if (attachedMedia.length >= MAX_MEDIA) return;
            if (!editorUpload || typeof editorUpload.uploadFile !== 'function') return;
            const cd = e.clipboardData || window.clipboardData;
            if (!cd) return;
            let file = null;
            if (cd.items && cd.items.length) {
                for (let i = 0; i < cd.items.length; i += 1) {
                    const it = cd.items[i];
                    if (!it) continue;
                    if (it.kind === 'file') {
                        const f = it.getAsFile && it.getAsFile();
                        if (f && (f.type?.startsWith('image/') || f.type?.startsWith('video/'))) {
                            file = f;
                            break;
                        }
                    }
                }
            }
            if (!file && cd.files && cd.files.length) {
                for (let i = 0; i < cd.files.length; i += 1) {
                    const f = cd.files[i];
                    if (f && (f.type?.startsWith('image/') || f.type?.startsWith('video/'))) {
                        file = f;
                        break;
                    }
                }
            }
            if (file) {
                e.preventDefault();
                await editorUpload.uploadFile(file);
            }
        } catch (_) { }
    };
    /* `opts.content` lets the caller swap in a transformed body string at
     * submit time without round-tripping through React state (which is
     * async). The default theme uses this to prepend a picker-attached
     * GIF/sticker URL to the body — same trick the comments editor uses
     * (see `useViewPost.handleSubmit`'s `${mediaUrl}\n\n${replyString}`).
     * Validation still runs against the resolved string. */
    const handleSubmit = async (event, opts = {}) => {
        event.preventDefault();
        setSubmitError('');
        const topic = topicValue;
        const title = String(titleValue).trim();
        let content = String(opts.content != null ? opts.content : contentValue).trim();
        const tag = tagEnabled ? String(tagValue || '').trim().toLowerCase() : '';

        // v1.12.0: Build media array from attached media items
        const media = attachedMedia.map(m => m.url).filter(Boolean);
        if (tagEnabled) {
            const validTags = TAG_OPTIONS_ENABLED.map(t => t.value);
            if (!validTags.includes(tag)) {
                setSubmitError("Invalid tag selected");
                return;
            }
            if (tag.length > 50) {
                setSubmitError("Tag too long");
                return;
            }
        }
        if (title === '') {
            setSubmitError("Title is required");
            return;
        }
        if (title.length > limits.maxTitle) {
            setSubmitError(`Title too long (${title.length} > ${limits.maxTitle} chars)`);
            return;
        }
        if (!topic || topic === '' || topic === '(select a topic)') {
            setSubmitError(`Please select or enter a community`);
            return;
        }
        if (topic.length < limits.minTopic) {
            setSubmitError(`Community name too short (min ${limits.minTopic} characters)`);
            return;
        }
        if (topic.length > limits.maxTopic) {
            setSubmitError(`Community name too long (max ${limits.maxTopic} characters)`);
            return;
        }
        if (content.length > limits.maxContent) {
            setSubmitError(`Content too long (${content.length} > ${limits.maxContent} chars)`);
            return;
        }
        if (!requireAccount('post')) {
            return;
        }
        setIsSubmitting(true);
        setSubmitStatus('solving');
        setSubmitStartTime(Date.now());
        try {
            if (isEditMode && overrideId) {
                const res = await tx.editPost(overrideId, {
                    topic,
                    title,
                    content,
                    target: '',
                    tag,
                    media
                });
                if (res && res.success) {
                    // Only navigate if user is still on this page
                    if (mountedRef.current) {
                        navigate(`/p/${overrideId}`);
                    }
                } else {
                    setSubmitError(formatError(res));
                    setIsSubmitting(false);
                    setSubmitStatus('idle');
                    setSubmitStartTime(null);
                }
                return;
            }
            const res = await tx.createPostAsync(topic, title, content, tag, media);
            if (res && res.success) {
                try {
                    const txHash = res && res.tx_hash ? String(res.tx_hash).toLowerCase() : "";
                    if (!txHash) throw new Error("missing tx hash");

                    const deriveYoutubeThumb = rawUrl => {
                        try {
                            const u = new URL(String(rawUrl || ''));
                            const host = (u.hostname || '').toLowerCase();
                            let id = null;
                            if (host === 'youtu.be' || host === 'www.youtu.be') {
                                const p = (u.pathname || '').replace(/^\//, '');
                                id = p ? p.split('/')[0].split('?')[0] : null;
                            } else if (host === 'www.youtube.com' || host === 'youtube.com' || host === 'm.youtube.com') {
                                if (u.pathname === '/watch') {
                                    id = new URLSearchParams(u.search).get('v');
                                } else if (u.pathname.startsWith('/embed/') || u.pathname.startsWith('/v/') || u.pathname.startsWith('/shorts/')) {
                                    const parts = u.pathname.split('/');
                                    id = parts[2] ? parts[2].split('?')[0] : null;
                                }
                            }
                            if (!id) return '';
                            return `https://img.youtube.com/vi/${id}/hqdefault.jpg`;
                        } catch (_) {
                            return '';
                        }
                    };
                    const firstLineUrl = (() => {
                        try {
                            const line = String(content || '').split('\n')[0]?.trim() || '';
                            return /^https?:\/\//i.test(line) ? line : '';
                        } catch (_) {
                            return '';
                        }
                    })();
                    const thumb = deriveYoutubeThumb(firstLineUrl) || (media.length > 0 ? media[0] : '');
                    const viewer = String(Storage.load("publicKey", "") || '').trim().toLowerCase();
                    const optimisticPost = {
                        post_id: txHash,
                        tx_hash: txHash,
                        author: viewer,
                        user_id: viewer,
                        username: Storage.load("username", ""),
                        timestamp: Math.floor(Date.now() / 1000),
                        topic,
                        title,
                        content,
                        target: '',
                        root_post_id: txHash,
                        tag,
                        media,
                        thumbnail: thumb,
                        direction: 1,
                        user_vote: 1,
                        user_weight: 1,
                        points: 1,
                        comments: 0,
                        deleted: false,
                    };

                    Storage.setPendingPostHighlight(txHash);
                    Storage.setOptimisticPost(optimisticPost);
                    try {
                        if (typeof setPosts === 'function') {
                            setPosts({ [txHash]: optimisticPost }, Date.now());
                        }
                    } catch (_) { }
                    console.debug('[CreatePostView] Optimistically showing post after broadcast', { txHash });
                    window.dispatchEvent(new CustomEvent('postCreated', {
                        detail: {
                            postId: txHash,
                            topic,
                            title,
                            content,
                            tag,
                            media,
                            thumbnail: thumb,
                            post: optimisticPost
                        }
                    }));
                    // Only navigate if user is still on this page
                    if (mountedRef.current) {
                        navigate(`/p/${txHash}`);
                    }
                    (async () => {
                        try {
                            const result = await tx.pollTxStatus(txHash);
                            if (!result) {
                                console.debug('[CreatePostView] Optimistic post still waiting for indexer', { txHash });
                                return;
                            }
                            if (!result.success) {
                                Storage.removeOptimisticPost(txHash);
                                const errorMessage = result.error_details?.message || 'transaction rejected';
                                console.error('[CreatePostView] Optimistic post transaction rejected', {
                                    txHash,
                                    error: errorMessage
                                });
                                updateNotification(`Post failed: ${errorMessage}`, 5, true);
                                window.dispatchEvent(new CustomEvent('postCreatedRejected', {
                                    detail: {
                                        postId: txHash,
                                        error: errorMessage
                                    }
                                }));
                                return;
                            }
                            const viewerAddress = Storage.load('publicKey', '');
                            const data = await Api.get('get_comments', {
                                post_id: txHash,
                                address: viewerAddress,
                                lens: 'effective',
                                scope: 'current',
                            });
                            if (data && data.root && Array.isArray(data.ancestors) && ('ancestors_omitted' in data)) {
                                Storage.removeOptimisticPost(txHash);
                                if (typeof setPosts === 'function') {
                                    setPosts({ [txHash]: data.root }, Date.now());
                                }
                                window.dispatchEvent(new CustomEvent('postCreatedIndexed', {
                                    detail: {
                                        postId: txHash,
                                        root: data.root,
                                        children: data.children || [],
                                        ancestors: data.ancestors,
                                        ancestors_omitted: data.ancestors_omitted,
                                    }
                                }));
                            } else if (data && data.root) {
                                console.error('[CreatePostView] get_comments missing ancestors', {
                                    txHash,
                                    keys: Object.keys(data),
                                });
                            }
                        } catch (e) {
                            console.debug('[CreatePostView] Background post reconciliation pending', {
                                txHash,
                                error: e?.message || String(e)
                            });
                        }
                    })();
                } catch (e) {
                    setSubmitError(String(e && e.message ? e.message : 'Failed to confirm transaction'));
                    setIsSubmitting(false);
                    setSubmitStatus('idle');
                    setSubmitStartTime(null);
                    return;
                }
            } else {
                setSubmitError(formatError(res));
                setIsSubmitting(false);
                setSubmitStatus('idle');
                setSubmitStartTime(null);
            }
        } catch (e) {
            console.error('[CreatePostView] submit failed:', e);
            setSubmitError(String(e?.message || e || (isEditMode ? 'edit failed' : 'post failed')));
            setIsSubmitting(false);
            setSubmitStatus('idle');
            setSubmitStartTime(null);
        }
    };
    return {
        location,
        isEditMode,
        overrideId,
        topicValue,
        titleValue,
        contentValue,
        setContentValue,
        submitError,
        setSubmitError,
        errorSetTimeRef,
        errorClearTimeoutRef,
        isSubmitting,
        submitStatus,
        editorUpload,
        setEditorUpload,
        globalDragging,
        setGlobalDragging,
        attachedMedia,
        setAttachedMedia,
        MAX_MEDIA,
        isUploading,
        setIsUploading,
        uploadProgress,
        setUploadProgress,
        thumbsLoading,
        setThumbsLoading,
        tagValue,
        setTagValue,
        tagEnabled,
        setTagEnabled,
        setTagManuallySet,
        titleInputRef,
        contentEditorRef,
        limits,
        handleTopicChange,
        getByteLength,
        handleTitleChange,
        getVideoThumbnailUrl,
        addMediaItem,
        handleTitlePaste,
        handleSubmit
    };
}
