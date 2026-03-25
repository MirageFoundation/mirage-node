import React from "react"
import { useState, useEffect } from 'react';
import { Helmet } from 'react-helmet-async';
import styled from "styled-components"
import { useNavigate, useLocation } from 'react-router-dom';
import { TopicSelector } from '../components/TopicSelector';
import * as tx from "../utils/tx.js";
import Api from '../lib/api';
import Storage from '../utils/Storage';
import MarkdownEditor from '../components/MarkdownEditor';
import Sidebar from "../components/Sidebar";
import TopBar from "../components/TopBar";
import Button from "../components/Button";
import MobileHeader from "../components/MobileHeader";
import { ContentGrid, ModernPostFeed, TabbedContainer, ContainerTab, ContainerBody } from "../styled/Layout";
import { MediaRow, MediaPreviewWrapper, MediaPreviewImage, MediaSpinner, MediaRemoveButton, MediaIconButton } from '../components/MediaAttachmentLayout';
import StickerPicker from '../components/StickerPicker';
import GifPicker from '../components/GifPicker';
import { formatError } from '../utils/errorMessages';

const Row = styled.div`
    display: grid;
    grid-template-columns: 5.5rem minmax(0, 1fr);
    gap: 0.5rem;
    align-items: start;
    margin: 0.5rem 0;
    
    &:not(:first-child) {
        margin-top: 1rem;
    }
    
    @media (max-width: 1000px) {
        grid-template-columns: 1fr;
        gap: 0.35rem;
        align-items: stretch;
    }
`;

const Label = styled.div`
    color: ${({ theme }) => theme?.colors?.subtleText || '#ccc'};
    font-weight: 600;
    font-size: 0.85rem;
    white-space: nowrap;
    padding-top: 8px;
    @media (max-width: 1000px) {
        display: none;
    }
`;

const ValueBox = styled.div`
    background-color: ${({ theme }) => theme?.colors?.panelAlt || '#1f2328'};
    border: 1px solid ${({ theme }) => theme?.colors?.border || '#444'};
    border-radius: 8px;
    padding: 0.6rem 0.85rem;
    width: 100%;
    box-sizing: border-box;
    overflow-x: auto;
`;

const StyledInputBox = styled.input`    
    border: 1px solid ${({ theme }) => theme?.colors?.border || '#444'};
    border-radius: 8px;
    background-color: ${({ theme }) => theme?.colors?.panelAlt || '#1f2328'};
    color: ${({ theme }) => theme?.colors?.text || '#FFFFFF'};
    font-size: 0.85rem;
    padding: 0.5rem 0.75rem;
    margin: 0;
    box-sizing: border-box;
    width: 100%;
    max-width: 100%;
    pointer-events: auto !important;
    transition: all 0.2s ease;
    outline: none;

    &:hover {
        border-color: ${({ theme }) => theme?.colors?.subtleText || '#666'};
    }
    &:focus {
        border-color: #667eea;
        box-shadow: 0 0 0 3px rgba(102, 126, 234, 0.15);
    }
    &:disabled {
        opacity: 0.5;
        cursor: not-allowed;
    }
    &::placeholder {
        color: ${({ theme }) => theme?.colors?.subtleText || '#888888'};
    }
`;

const StyledSelect = styled.select`
    border: 1px solid ${({ theme }) => theme?.colors?.border || '#444'};
    border-radius: 8px;
    background-color: ${({ theme }) => theme?.colors?.panelAlt || '#1f2328'};
    color: ${({ theme }) => theme?.colors?.text || '#FFFFFF'};
    font-size: 0.85rem;
    padding: 0.5rem 0.75rem;
    margin: 0;
    box-sizing: border-box;
    width: 100%;
    max-width: 100%;
    pointer-events: auto !important;
    transition: all 0.2s ease;
    outline: none;

    &:hover {
        border-color: ${({ theme }) => theme?.colors?.subtleText || '#666'};
    }
    &:focus {
        border-color: #667eea;
        box-shadow: 0 0 0 3px rgba(102, 126, 234, 0.15);
    }
    &:disabled {
        opacity: 0.5;
        cursor: not-allowed;
    }
`;

const ContentActionsRow = styled.div`
    display: flex;
    align-items: center;
    justify-content: space-between;
    width: 100%;
    gap: 0.5rem;
    flex-wrap: nowrap;
    margin-top: 0.2rem;
`;

const ContentCounter = styled.span`
    font-size: 0.45rem;
    color: ${props => props.$warn ? '#ff6b6b' : '#888'};
    margin-left: 0.15rem;
    margin-top: -0.05rem;
`;

const GlobalDropOverlay = styled.div`
    position: absolute;
    inset: 0;
    border: 2px dashed #667eea;
    border-radius: 12px;
    background-color: rgba(102, 126, 234, 0.15);
    display: flex;
    align-items: center;
    justify-content: center;
    pointer-events: none;
    z-index: 5;
    color: #667eea;
    font-size: 0.9rem;
    font-weight: 600;
`;

const HelpText = styled.div`
    font-size: 0.65rem;
    font-style: italic;
    color: ${({ theme }) => theme?.colors?.subtleText || '#888'};
    margin-top: 0.35rem;
    margin-left: 0.2rem;
    margin-right: 0.2rem;
    text-align: justify;
    line-height: 1.4;
`;

const Mono = styled.span`
    color: ${({ theme }) => theme?.colors?.text || '#eee'};
    font-size: 0.75rem;
    font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
    white-space: normal;
    word-break: break-all;
    overflow-wrap: anywhere;
`;

const ErrorMessage = styled.div`
    background-color: rgba(220, 38, 38, 0.1);
    border: 1px solid #dc2626;
    border-radius: 6px;
    padding: 0.5rem 0.75rem;
    margin-top: 0.5rem;
    color: #dc2626;
    font-size: 0.8rem;
    display: flex;
    align-items: center;
    gap: 0.5rem;
`;

const CharCounter = styled.span`
    font-size: 0.45rem;
    color: ${({ $warn, theme }) => $warn ? '#ff6b6b' : '#888'};
    margin-left: 0.15rem;
    margin-top: 0.15rem;    
`;

const TAG_OPTIONS = [
    { value: '', label: 'No tag (safe)' },
    { value: 'sensitive', label: 'Sensitive (blur content)' },
    { value: 'porn', label: 'Porn' },
    { value: 'violence', label: 'Violence' },
    { value: 'gore', label: 'Gore' },
    { value: 'death', label: 'Death' },
];
const TAG_OPTIONS_ENABLED = TAG_OPTIONS.filter((t) => t.value);

const TagToggle = styled.label`
    display: inline-flex;
    align-items: center;
    gap: 0.5rem;
    font-size: 0.9rem;
    color: ${({ theme }) => theme?.colors?.text || '#fff'};

    input {
        accent-color: #667eea;
        width: 1rem;
        height: 1rem;
    }
`;

function CreatePostView({ state, setPosts, updatePost }) {
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
        return () => { mountedRef.current = false; };
    }, []);

    const isSafeImageUrl = (url) => {
        try {
            const u = new URL(url);
            const host = u.hostname.toLowerCase();
            const p = u.pathname.toLowerCase();
            const isCloudflareImage = host.endsWith('imagedelivery.net');
            const isRasterExt = p.endsWith('.png') || p.endsWith('.jpg') || p.endsWith('.jpeg') || p.endsWith('.gif') || p.endsWith('.webp') || p.endsWith('.bmp') || p.endsWith('.avif');
            return isCloudflareImage || isRasterExt;
        } catch (_) { return false; }
    };

    const isSafeVideoUrl = (url) => {
        try {
            const u = new URL(url);
            const p = u.pathname.toLowerCase();
            const host = u.hostname.toLowerCase();
            const isStream = host.endsWith('cloudflarestream.com') || host.endsWith('videodelivery.net');
            const isVidExt = p.endsWith('.mp4') || p.endsWith('.webm') || p.endsWith('.ogv') || p.endsWith('.mov') || p.endsWith('.mkv') || p.endsWith('.gifv');
            return isStream || isVidExt;
        } catch (_) { return false; }
    };

    useEffect(() => {
        if (!isEditMode || !overrideId) return;
        const load = async () => {
            try {
                const viewerAddress = Storage.load('publicKey', '');
                const data = await Api.get('get_comments', { post_id: overrideId, address: viewerAddress });
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
                            const type = isSafeVideoUrl(url) ? 'video' : 'image';
                            return { type, url };
                        });
                        setAttachedMedia(items);
                        setThumbsLoading(new Set(items.map(m => m.url)));
                        setContentValue(content);
                    } else {
                        // Legacy: extract first-line media from content
                        const lines = content.split('\n');
                        const firstLine = lines[0]?.trim() || '';
                        if (/^https?:\/\//i.test(firstLine)) {
                            const isImage = isSafeImageUrl(firstLine);
                            const isVideo = isSafeVideoUrl(firstLine);
                            if (isImage || isVideo) {
                                setAttachedMedia([{ type: isImage ? 'image' : 'video', url: firstLine }]);
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

    useEffect(() => {
        const handleStorageChange = (e) => {
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
        if (!tx.needsChainConfigRefresh()) return;
        Api.get('get_chain_config', undefined)
            .then((cfg) => { if (cfg) try { tx.cacheChainConfig(cfg); } catch (_) { } })
            .catch(() => { });
    }, []);

    // eslint-disable-next-line react-hooks/exhaustive-deps
    const limits = React.useMemo(() => {
        void configUpdateTrigger;
        try {
            const chainRaw = localStorage.getItem('chainConfig');
            const chain = JSON.parse(chainRaw || '{}');
            const userLevel = parseInt(Storage.load('user_level', '0'));
            const tiers = chain.tiers || [];
            const tierIndex = userLevel === 0 ? 0 : userLevel === 1 ? 1 : (userLevel === 10 || userLevel >= 100) ? 2 : 0;
            const tier = tiers[tierIndex] || {};

            // Get limits from chain params tiers, with sensible fallbacks
            const maxTitle = parseInt(tier.max_title_length) || 130;
            const maxContent = parseInt(tier.max_content_length) || 1000;

            return {
                maxTitle,
                maxContent,
                maxTopic: parseInt(chain.max_topic_size) || 50,
                minTopic: parseInt(chain.min_topic_size) || 2,
                willPayFee: userLevel >= 1
            };
        } catch (e) {
            console.error('[CreatePostView] Error calculating limits:', e);
            return { maxTitle: 130, maxContent: 1000, maxTopic: 50, minTopic: 2, willPayFee: false };
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


    const handleTopicChange = (e) => {
        let formattedValue = e.target.value
            .replace(/[^a-zA-Z0-9]/g, '')
            .toLowerCase();
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
        const meta = e.meta || {};
        const dominantTag = (meta.dominant_tag || '').toLowerCase();
        const topicChanged = formattedValue !== prevTopic;
        if (dominantTag) {
            // Only auto-apply dominant tag if user hasn't manually set one
            if (!tagManuallySet) {
                setTagEnabled(true);
                setTagValue(dominantTag);
                setTagManuallySet(false);
            }
        } else if (topicChanged) {
            // Do NOT clear existing content warning when switching topics
            // Leave tagEnabled/tagValue as-is unless user changes it manually
        }
        if (submitError) setSubmitError('');
    };

    // Count UTF-8 bytes (Go's len() counts bytes, not characters)
    const getByteLength = (str) => new TextEncoder().encode(str).length;

    const handleTitleChange = (e) => {
        let value = e.target.value;
        // Truncate by removing characters until byte length is within limit
        while (getByteLength(value) > limits.maxTitle && value.length > 0) {
            value = value.slice(0, -1);
        }
        setTitleValue(value);
        if (submitError) setSubmitError('');
    };

    const getVideoThumbnailUrl = (url) => {
        try {
            if (!url) return null;
            const u = new URL(url);
            const parts = u.pathname.split('/').filter(Boolean);
            const uid = parts[0];
            if (!uid) return null;
            return `${u.origin}/${uid}/thumbnails/thumbnail.jpg`;
        } catch (_) {
            return null;
        }
    };

    // Helper: add a media item and mark its URL as loading a thumbnail
    const addMediaItem = (type, url) => {
        setAttachedMedia(prev => {
            if (prev.length >= MAX_MEDIA) return prev;
            return [...prev, { type, url }];
        });
        setThumbsLoading(prev => { const n = new Set(prev); n.add(url); return n; });
    };

    const handleTitlePaste = async (e) => {
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

    const handleSubmit = async (event) => {
        event.preventDefault();
        setSubmitError('');
        const topic = topicValue;
        const title = String(titleValue).trim();
        let content = String(contentValue).trim();
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
            setSubmitError(`Please select or enter a topic`);
            return;
        }

        if (topic.length < limits.minTopic) {
            setSubmitError(`Topic too short (min ${limits.minTopic} characters)`);
            return;
        }

        if (topic.length > limits.maxTopic) {
            setSubmitError(`Topic too long (max ${limits.maxTopic} characters)`);
            return;
        }

        if (content.length > limits.maxContent) {
            setSubmitError(`Content too long (${content.length} > ${limits.maxContent} chars)`);
            return;
        }

        if (!state.publicKey) {
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
                    media,
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
                    const txHash = (res && res.tx_hash) ? String(res.tx_hash).toLowerCase() : "";
                    if (!txHash) throw new Error("missing tx hash");

                    // Stage 2: Submitting (show for 1-1.5 seconds)
                    setSubmitStatus('submitting');
                    setSubmitStartTime(Date.now());
                    const submittingDuration = 1000 + Math.random() * 500; // 1.0 to 1.5 seconds
                    await new Promise(r => setTimeout(r, submittingDuration));

                    // Stage 3: Verifying (4s initial, then 2s intervals, max 5 attempts)
                    setSubmitStatus('verifying');
                    setSubmitStartTime(Date.now());
                    const result = await tx.pollTxStatus(txHash);
                    if (!result) throw new Error('confirmation timeout');
                    if (!result.success) {
                        throw new Error(result.error_details?.message || 'transaction rejected');
                    }

                    // Set the pending highlight so the post flashes when viewed
                    Storage.setPendingPostHighlight(txHash);
                    // Emit event for immediate flash in any listening view
                    const deriveYoutubeThumb = (rawUrl) => {
                        try {
                            const u = new URL(String(rawUrl || ''));
                            const host = (u.hostname || '').toLowerCase();
                            let id = null;
                            if (host === 'youtu.be' || host === 'www.youtu.be') {
                                const p = (u.pathname || '').replace(/^\//, '');
                                id = p ? p.split('/')[0].split('?')[0] : null;
                            } else if (host === 'www.youtube.com' || host === 'youtube.com' || host === 'm.youtube.com') {
                                if (u.pathname === '/watch') {
                                    id = (new URLSearchParams(u.search)).get('v');
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
                        } catch (_) { return ''; }
                    })();
                    const thumb = deriveYoutubeThumb(firstLineUrl)
                        || (media.length > 0 ? media[0] : '');
                    window.dispatchEvent(new CustomEvent('postCreated', {
                        detail: {
                            postId: txHash,
                            topic,
                            title,
                            content,
                            tag,
                            media,
                            thumbnail: thumb,
                        }
                    }));
                    // Only navigate if user is still on this page
                    if (mountedRef.current) {
                        navigate(`/p/${txHash}`);
                    }
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
    }

    return (
        <ContentGrid>
            <Helmet>
                <title>{isEditMode ? 'Edit Post' : 'Create Post'} | Mirage</title>
            </Helmet>
            <Sidebar currentPath={location.pathname} state={state} />
            <div>
                <TopBar state={state} />
                <ModernPostFeed>
                    <MobileHeader />
                    <TabbedContainer>
                        <ContainerTab>{isEditMode ? 'Edit Post' : 'Create Post'}</ContainerTab>
                        <ContainerBody
                            style={{ position: 'relative' }}
                            onDragOver={(e) => {
                                try {
                                    if (isUploading) return;
                                    const types = Array.from((e && e.dataTransfer && e.dataTransfer.types) || []);
                                    if (!types.includes('Files')) return;
                                    e.preventDefault();
                                    e.stopPropagation();
                                    if (!globalDragging) setGlobalDragging(true);
                                } catch (_) { }
                            }}
                            onDragLeave={(e) => {
                                try {
                                    if (isUploading) return;
                                    const types = Array.from((e && e.dataTransfer && e.dataTransfer.types) || []);
                                    if (!types.includes('Files')) return;
                                    e.preventDefault();
                                    e.stopPropagation();
                                    if (!(e.currentTarget.contains(e.relatedTarget))) setGlobalDragging(false);
                                } catch (_) { }
                            }}
                            onDrop={(e) => {
                                try {
                                    if (isUploading || attachedMedia.length >= MAX_MEDIA) {
                                        e.preventDefault();
                                        e.stopPropagation();
                                        return;
                                    }
                                    const files = Array.from((e && e.dataTransfer && e.dataTransfer.files) || []);
                                    if (!files || files.length === 0) return;
                                    e.preventDefault();
                                    e.stopPropagation();
                                    setGlobalDragging(false);
                                    if (editorUpload && typeof editorUpload.uploadFile === 'function') {
                                        editorUpload.uploadFile(files[0]);
                                    }
                                } catch (_) { }
                            }}
                        >
                            <form
                                id="create-post-form"
                                onSubmit={handleSubmit}
                                autoComplete="off"
                                onKeyDown={(e) => {
                                    if (e.key !== 'Tab') return;
                                    const form = e.currentTarget;
                                    const focusable = form.querySelectorAll(
                                        'input:not([type="hidden"]):not([tabindex="-1"]):not(:disabled), textarea:not(:disabled), button[type="submit"]:not(:disabled)'
                                    );
                                    if (focusable.length === 0) return;
                                    const first = focusable[0];
                                    const last = focusable[focusable.length - 1];
                                    if (e.shiftKey && document.activeElement === first) {
                                        e.preventDefault();
                                        last.focus();
                                    } else if (!e.shiftKey && document.activeElement === last) {
                                        e.preventDefault();
                                        first.focus();
                                    }
                                }}
                            >
                                {isEditMode && (
                                    <Row>
                                        <Label>Tx Hash:</Label>
                                        <ValueBox>
                                            <Mono>{overrideId}</Mono>
                                        </ValueBox>
                                    </Row>
                                )}
                                <Row>
                                    <Label>Topic:</Label>
                                    <div>
                                        <TopicSelector
                                            value={topicValue}
                                            maxLength={limits.maxTopic}
                                            minLength={limits.minTopic}
                                            onChange={handleTopicChange}
                                            disabled={isSubmitting}
                                            aria-label="Topic"
                                        />
                                        <HelpText>
                                            Topics are communities centered around specific interests. Posting in the wrong topic may affect your overall trust status on Mirage. <b>Make sure to post into the right category!</b>
                                        </HelpText>
                                    </div>
                                </Row>
                                <Row>
                                    <Label>Title:</Label>
                                    <div style={{ display: 'flex', flexDirection: 'column' }}>
                                        <StyledInputBox
                                            ref={titleInputRef}
                                            name="title"
                                            id="title"
                                            value={titleValue}
                                            placeholder="Title of your post"
                                            onPaste={handleTitlePaste}
                                            autoComplete="off"
                                            autoCorrect="on"
                                            autoCapitalize="sentences"
                                            spellCheck={true}
                                            maxLength={limits.maxTitle}
                                            onChange={handleTitleChange}
                                            disabled={isSubmitting}
                                            aria-label="Title"
                                            onKeyDown={(e) => {
                                                if (e.key === 'Enter') {
                                                    e.preventDefault();
                                                    if (contentEditorRef.current) contentEditorRef.current.focus();
                                                }
                                            }}
                                        />
                                        {!isSubmitting && (
                                            <CharCounter $warn={getByteLength(titleValue) >= limits.maxTitle}>
                                                {getByteLength(titleValue)} / {limits.maxTitle} {limits.willPayFee ? '(paid tier)' : '(free tier)'}
                                            </CharCounter>
                                        )}
                                    </div>
                                </Row>
                                <Row style={{ alignItems: 'flex-start' }}>
                                    <Label style={{ paddingTop: '1px' }}>Tag:</Label>
                                    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.35rem' }}>
                                        <TagToggle>
                                            <input
                                                type="checkbox"
                                                tabIndex={-1}
                                                checked={tagEnabled}
                                                onChange={(e) => {
                                                    const enabled = e.target.checked;
                                                    setTagEnabled(enabled);
                                                    if (enabled) {
                                                        setTagValue((prev) => prev || TAG_OPTIONS_ENABLED[0]?.value || 'sensitive');
                                                        setTagManuallySet(true);
                                                    } else {
                                                        setTagValue('');
                                                        setTagManuallySet(true);
                                                    }
                                                    if (submitError) setSubmitError('');
                                                }}
                                                disabled={isSubmitting}
                                                aria-label="Add content warning"
                                            />
                                            Add content warning
                                        </TagToggle>
                                        {tagEnabled && (
                                            <>
                                                <StyledSelect
                                                    tabIndex={-1}
                                                    value={tagValue}
                                                    onChange={(e) => {
                                                        setTagValue(e.target.value);
                                                        setTagManuallySet(true);
                                                        if (submitError) setSubmitError('');
                                                    }}
                                                    disabled={isSubmitting}
                                                    aria-label="Content tag"
                                                >
                                                    {TAG_OPTIONS_ENABLED.map((opt) => (
                                                        <option key={opt.value || 'none'} value={opt.value}>{opt.label}</option>
                                                    ))}
                                                </StyledSelect>
                                                <HelpText>
                                                    Optional content warning. Choose a tag if the post contains sensitive material.
                                                </HelpText>
                                            </>
                                        )}
                                    </div>
                                </Row>
                                <Row>
                                    <Label>Media:</Label>
                                    <MediaRow>
                                        <StickerPicker
                                            onSelect={(stickerUrl) => {
                                                if (attachedMedia.length >= MAX_MEDIA) return;
                                                addMediaItem('image', stickerUrl);
                                            }}
                                            disabled={isSubmitting || isUploading || attachedMedia.length >= MAX_MEDIA}
                                        />
                                        <GifPicker
                                            onSelect={(gifUrl) => {
                                                if (attachedMedia.length >= MAX_MEDIA) return;
                                                addMediaItem('image', gifUrl);
                                            }}
                                            disabled={isSubmitting || isUploading || attachedMedia.length >= MAX_MEDIA}
                                        />
                                        <MediaIconButton
                                            type="button"
                                            tabIndex={-1}
                                            onClick={() => { try { editorUpload && editorUpload.selectFile(); } catch (_) { } }}
                                            disabled={isSubmitting || isUploading || attachedMedia.length >= MAX_MEDIA}
                                            aria-label="Upload"
                                            title="Upload"
                                        >
                                            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                                                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                                                <polyline points="17 8 12 3 7 8" />
                                                <line x1="12" y1="3" x2="12" y2="15" />
                                            </svg>
                                        </MediaIconButton>
                                        {attachedMedia.length > 0 && (
                                            <span style={{ fontSize: '0.65rem', color: '#888' }}>
                                                {attachedMedia.length}/{MAX_MEDIA}
                                            </span>
                                        )}
                                        {attachedMedia.map((item, idx) => (
                                            <MediaPreviewWrapper key={`${item.url}-${idx}`}>
                                                <MediaPreviewImage
                                                    src={item.type === 'image' ? item.url : (getVideoThumbnailUrl(item.url) || item.url)}
                                                    alt=""
                                                    onLoad={() => {
                                                        setThumbsLoading(prev => { const n = new Set(prev); n.delete(item.url); return n; });
                                                    }}
                                                    onError={() => {
                                                        setThumbsLoading(prev => { const n = new Set(prev); n.delete(item.url); return n; });
                                                    }}
                                                />
                                                {thumbsLoading.has(item.url) && (
                                                    <MediaSpinner />
                                                )}
                                                <MediaRemoveButton
                                                    type="button"
                                                    tabIndex={-1}
                                                    disabled={isSubmitting}
                                                    onClick={() => {
                                                        if (isSubmitting) return;
                                                        setAttachedMedia(prev => prev.filter((_, i) => i !== idx));
                                                    }}
                                                    aria-label="Remove attached media"
                                                    title="Remove attached media"
                                                >
                                                    ×
                                                </MediaRemoveButton>
                                            </MediaPreviewWrapper>
                                        ))}
                                        {isUploading && (
                                            <MediaPreviewWrapper>
                                                <div style={{ width: '100%', height: '100%', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', padding: '0.5rem', boxSizing: 'border-box' }}>
                                                    <span style={{ fontSize: '0.7rem', color: '#888', marginBottom: '0.25rem' }}>
                                                        Uploading {uploadProgress !== null ? `${Math.round(uploadProgress)}%` : '...'}
                                                    </span>
                                                    <Button
                                                        variant="danger"
                                                        size="xs"
                                                        tabIndex={-1}
                                                        onClick={() => {
                                                            try {
                                                                if (editorUpload && editorUpload.cancelUpload) {
                                                                    editorUpload.cancelUpload();
                                                                }
                                                            } catch (_) { }
                                                        }}
                                                    >
                                                        Cancel
                                                    </Button>
                                                </div>
                                            </MediaPreviewWrapper>
                                        )}
                                    </MediaRow>
                                </Row>
                                <Row>
                                    <Label>Content:</Label>
                                    <div style={{ display: 'flex', flexDirection: 'column' }}>
                                        <MarkdownEditor
                                            value={contentValue}
                                            onChange={(v) => {
                                                setContentValue(v);
                                            }}
                                            maxLength={limits.maxContent}
                                            disabled={isSubmitting}
                                            uploadBlocked={attachedMedia.length >= MAX_MEDIA}
                                            onSubmitShortcut={() => {
                                                try {
                                                    const form = document.getElementById('create-post-form');
                                                    if (form) form.requestSubmit();
                                                } catch (_) { }
                                            }}
                                            showCounters={false}
                                            renderHelperRow={false}
                                            toolbarButtonSize="1.5rem"
                                            toolbarIconSize="0.95rem"
                                            minHeight="10rem"
                                            registerUploadHandler={setEditorUpload}
                                            editorRef={(ref) => { contentEditorRef.current = ref; }}
                                            belowElement={
                                                submitError ? (
                                                    <ErrorMessage role="alert">{submitError}</ErrorMessage>
                                                ) : null
                                            }
                                            onMediaUploaded={(type, url, error) => {
                                                if (error) {
                                                    if (errorClearTimeoutRef.current) {
                                                        clearTimeout(errorClearTimeoutRef.current);
                                                        errorClearTimeoutRef.current = null;
                                                    }
                                                    errorSetTimeRef.current = Date.now();
                                                    setSubmitError(error);
                                                    errorClearTimeoutRef.current = setTimeout(() => {
                                                        setSubmitError('');
                                                        errorSetTimeRef.current = null;
                                                        errorClearTimeoutRef.current = null;
                                                    }, 5000);
                                                } else if (!type || !url) {
                                                    if (errorClearTimeoutRef.current) {
                                                        clearTimeout(errorClearTimeoutRef.current);
                                                        errorClearTimeoutRef.current = null;
                                                    }
                                                    errorSetTimeRef.current = Date.now();
                                                    setSubmitError('Media upload failed. Please try again.');
                                                    errorClearTimeoutRef.current = setTimeout(() => {
                                                        setSubmitError('');
                                                        errorSetTimeRef.current = null;
                                                        errorClearTimeoutRef.current = null;
                                                    }, 5000);
                                                } else {
                                                    addMediaItem(type, url);
                                                }
                                            }}
                                            onUploadStateChange={(uploading) => {
                                                setIsUploading(uploading);
                                                if (!uploading) {
                                                    setUploadProgress(null);
                                                }
                                            }}
                                            onUploadProgress={(progress) => {
                                                setUploadProgress(progress);
                                            }}
                                            suffixLabel={limits.willPayFee ? '(paid tier)' : '(free tier)'}
                                        />
                                        <ContentActionsRow>
                                            <div style={{ display: 'flex', flexDirection: 'column', gap: '2px', minWidth: 0, flex: '1 1 auto', alignSelf: 'flex-start' }}>
                                                <ContentCounter $warn={contentValue.length >= limits.maxContent}>
                                                    {contentValue.length} / {limits.maxContent} {limits.willPayFee ? '(paid tier)' : '(free tier)'}
                                                </ContentCounter>
                                            </div>
                                            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                                                <Button
                                                    type="submit"
                                                    disabled={isSubmitting || isUploading}
                                                    loading={isSubmitting}
                                                    mobileFullWidth
                                                >
                                                    {isSubmitting
                                                        ? (submitStatus === 'verifying' ? 'Verifying...' :
                                                            submitStatus === 'submitting' ? 'Submitting...' :
                                                                'Processing')
                                                        : (isEditMode ? 'Save Edit' : 'Submit')}
                                                </Button>
                                            </div>
                                        </ContentActionsRow>
                                    </div>
                                </Row>
                            </form>
                            {globalDragging && (
                                <GlobalDropOverlay>Drop image/video to upload</GlobalDropOverlay>
                            )}
                        </ContainerBody>
                    </TabbedContainer>
                </ModernPostFeed>
            </div>
        </ContentGrid>
    )
}

export default CreatePostView
