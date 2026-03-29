import React from "react";
import { useState, useEffect } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import * as tx from "../utils/tx.js";
import Api from "../lib/api";
import Storage from "../utils/Storage";
import { formatError } from "../utils/errorMessages";
export const TAG_OPTIONS = [{
  value: '',
  label: 'No tag (safe)'
}, {
  value: 'sensitive',
  label: 'Sensitive (blur content)'
}, {
  value: 'porn',
  label: 'Porn'
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
    } catch (_) {}
    return null;
  };
  const getPreferredTopic = React.useCallback(() => {
    try {
      const st = locationState && locationState.fromTopic;
      if (st && st !== 'all') {
        return String(st).replace(/[^a-zA-Z0-9]/g, '').toLowerCase();
      }
    } catch (_) {}
    try {
      const params = new URLSearchParams(locationSearch || '');
      const qp = params.get('topic');
      if (qp && qp !== 'all') {
        return String(qp).replace(/[^a-zA-Z0-9]/g, '').toLowerCase();
      }
    } catch (_) {}
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
    return () => {
      mountedRef.current = false;
    };
  }, []);
  const isSafeImageUrl = url => {
    try {
      const u = new URL(url);
      const host = u.hostname.toLowerCase();
      const p = u.pathname.toLowerCase();
      const isCloudflareImage = host.endsWith('imagedelivery.net');
      const isRasterExt = p.endsWith('.png') || p.endsWith('.jpg') || p.endsWith('.jpeg') || p.endsWith('.gif') || p.endsWith('.webp') || p.endsWith('.bmp') || p.endsWith('.avif');
      return isCloudflareImage || isRasterExt;
    } catch (_) {
      return false;
    }
  };
  const isSafeVideoUrl = url => {
    try {
      const u = new URL(url);
      const p = u.pathname.toLowerCase();
      const host = u.hostname.toLowerCase();
      const isStream = host.endsWith('cloudflarestream.com') || host.endsWith('videodelivery.net');
      const isVidExt = p.endsWith('.mp4') || p.endsWith('.webm') || p.endsWith('.ogv') || p.endsWith('.mov') || p.endsWith('.mkv') || p.endsWith('.gifv');
      return isStream || isVidExt;
    } catch (_) {
      return false;
    }
  };
  useEffect(() => {
    if (!isEditMode || !overrideId) return;
    const load = async () => {
      try {
        const viewerAddress = Storage.load('publicKey', '');
        const data = await Api.get('get_comments', {
          post_id: overrideId,
          address: viewerAddress
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
              const type = isSafeVideoUrl(url) ? 'video' : 'image';
              return {
                type,
                url
              };
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
    if (!tx.needsChainConfigRefresh()) return;
    Api.get('get_chain_config', undefined).then(cfg => {
      if (cfg) try {
        tx.cacheChainConfig(cfg);
      } catch (_) {}
    }).catch(() => {});
  }, []);

  // eslint-disable-next-line react-hooks/exhaustive-deps
  const limits = React.useMemo(() => {
    void configUpdateTrigger;
    try {
      const chainRaw = localStorage.getItem('chainConfig');
      const chain = JSON.parse(chainRaw || '{}');
      const userLevel = parseInt(Storage.load('user_level', '0'));
      const tiers = chain.tiers || [];
      const tierIndex = userLevel === 0 ? 0 : userLevel === 1 ? 1 : userLevel === 10 || userLevel >= 100 ? 2 : 0;
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
      return {
        maxTitle: 130,
        maxContent: 1000,
        maxTopic: 50,
        minTopic: 2,
        willPayFee: false
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
  const getVideoThumbnailUrl = url => {
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
    } catch (_) {}
  };
  const handleSubmit = async event => {
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
          window.dispatchEvent(new CustomEvent('postCreated', {
            detail: {
              postId: txHash,
              topic,
              title,
              content,
              tag,
              media,
              thumbnail: thumb
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