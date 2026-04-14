import { Helmet } from "react-helmet-async";
import styled from "styled-components";
import { TopicSelector } from "../components/TopicSelector.js";
import MarkdownEditor from "../components/MarkdownEditor.js";
import Button from "../components/Button.js";
import LoggedOutPromptCard from "../components/LoggedOutPromptCard.js";
import { ContentGrid, ModernPostFeed, TabbedContainer, ContainerTab, ContainerBody, CappedPageColumn } from "../Layout";
import { MediaRow, MediaPreviewWrapper, MediaPreviewImage, MediaSpinner, MediaRemoveButton, MediaIconButton } from "../components/MediaAttachmentLayout.js";
import StickerPicker from "../components/StickerPicker.js";
import GifPicker from "../components/GifPicker.js";
import { useCreatePost, TAG_OPTIONS_ENABLED } from "../../../logic/useCreatePost";

const Row = styled.div`
    display: grid;
    grid-template-columns: 5.5rem minmax(0, 1fr);
    gap: ${({
    theme
}) => theme.layout.formRowGap};
    align-items: start;
    margin: ${({
    theme
}) => theme.layout.formRowMargin};
    
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
    color: ${({
    theme
}) => theme.colors.subtleText};
    font-weight: ${({
    theme
}) => theme.layout.labelWeight};
    font-size: ${({
    theme
}) => theme.layout.labelSize};
    white-space: nowrap;
    padding-top: ${({
    theme
}) => theme.layout.labelPaddingTop};
    @media (max-width: 1000px) {
        display: none;
    }
`;
const ValueBox = styled.div`
    background-color: ${({
    theme
}) => theme.layout.containerBg};
    border: ${({
    theme
}) => theme.layout.containerBorder};
    border-bottom: ${({
    theme
}) => theme.layout.containerBorderBottom};
    border-radius: ${({
    theme
}) => theme.layout.containerRadius};
    padding: ${({
    theme
}) => theme.layout.containerPaddingCompact};
    width: 100%;
    box-sizing: border-box;
    overflow-x: auto;
`;
const StyledInputBox = styled.input`    
    border: 1px solid ${({
    theme
}) => theme.colors.border};
    border-radius: ${({
    theme
}) => theme.layout.inputRadius};
    background-color: ${({
    theme
}) => theme.colors.panelAlt};
    color: ${({
    theme
}) => theme.colors.text};
    font-size: ${({
    theme
}) => theme.layout.inputSize};
    line-height: 1.25;
    padding: ${({
    theme
}) => theme.layout.inputPadding};
    margin: 0;
    box-sizing: border-box;
    width: 100%;
    max-width: 100%;
    pointer-events: auto !important;
    transition: all 0.2s ease;
    outline: none;

    &:hover {
        border-color: ${({
    theme
}) => theme.colors.subtleText};
    }
    &:focus {
        border-color: #667eea;
        box-shadow: ${({
    theme
}) => theme.layout.focusRing};
    }
    &:disabled {
        opacity: 0.5;
        cursor: not-allowed;
    }
    &::placeholder {
        color: ${({
    theme
}) => theme.colors.subtleText};
    }
`;
const StyledSelect = styled.select`
    border: 1px solid ${({
    theme
}) => theme.colors.border};
    border-radius: ${({
    theme
}) => theme.layout.inputRadius};
    background-color: ${({
    theme
}) => theme.colors.panelAlt};
    color: ${({
    theme
}) => theme.colors.text};
    font-size: ${({
    theme
}) => theme.layout.inputSize};
    line-height: 1.25;
    padding: ${({
    theme
}) => theme.layout.inputPadding};
    margin: 0;
    box-sizing: border-box;
    width: 100%;
    max-width: 100%;
    pointer-events: auto !important;
    transition: all 0.2s ease;
    outline: none;

    &:hover {
        border-color: ${({
    theme
}) => theme.colors.subtleText};
    }
    &:focus {
        border-color: #667eea;
        box-shadow: ${({
    theme
}) => theme.layout.focusRing};
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
    font-size: ${({ theme }) => theme.layout.bodySize};
    font-weight: 600;
`;
const HelpText = styled.div`
    font-size: ${({ theme }) => theme.layout.smallSize};
    font-style: italic;
    color: ${({ theme }) => theme.colors.subtleText};
    margin-top: 0.35rem;
    margin-left: 0.2rem;
    margin-right: 0.2rem;
    text-align: justify;
    line-height: 1.4;
`;
const Mono = styled.span`
    color: ${({
    theme
}) => theme.colors.text};
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
    color: ${({
    $warn,
    theme
}) => $warn ? '#ff6b6b' : '#888'};
    margin-left: 0.15rem;
    margin-top: 0.15rem;    
`;
const TagToggle = styled.label`
    display: inline-flex;
    align-items: center;
    gap: 0.4rem;
    font-size: ${({ theme }) => theme.layout.inputSize};
    line-height: 1.25;
    font-weight: 400;
    color: ${({ theme }) => theme.colors.text};

    input {
        accent-color: #667eea;
        width: 0.85rem;
        height: 0.85rem;
        flex-shrink: 0;
    }
`;
function CreatePostView({
    state,
    setPosts,
    updatePost
}) {
    const isLoggedIn = !!(state && state.publicKey && state.publicKey !== 'guest');
    if (!isLoggedIn) {
        return <ContentGrid>
            <Helmet>
                <title>Create Post | Mirage</title>
            </Helmet>
            <div>
                <ModernPostFeed>
                    <LoggedOutPromptCard
                        role="region"
                        aria-label="Create a post on Mirage"
                        eyebrow="Create post"
                        title="Sign in to post on Mirage"
                        description="Create an account or sign in to publish posts, join topics, and participate on-chain."
                        links={[
                            { label: 'Watch Introduction (YouTube)', href: 'https://www.youtube.com/watch?v=TOvP32ihQ0M', external: true },
                            { label: 'Learn More', href: 'https://mirage.foundation', external: true },
                        ]}
                        inviteText="Have an invite code? Join the community today."
                        primaryLabel="Create account"
                        secondaryLabel="Sign in"
                    />
                </ModernPostFeed>
            </div>
        </ContentGrid>;
    }
    return <CreatePostAuthenticated state={state} setPosts={setPosts} updatePost={updatePost} />;
}

function CreatePostAuthenticated({
    state,
    setPosts,
    updatePost
}) {
    const {
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
    } = useCreatePost({
        state,
        setPosts,
        updatePost
    });
    return <ContentGrid>
        <Helmet>
            <title>{isEditMode ? 'Edit Post' : 'Create Post'} | Mirage</title>
        </Helmet>
        <CappedPageColumn>
            <ModernPostFeed>
                <TabbedContainer>
                    <ContainerTab>{isEditMode ? 'Edit Post' : 'Create Post'}</ContainerTab>
                    <ContainerBody style={{
                        position: 'relative'
                    }} onDragOver={e => {
                        try {
                            if (isUploading) return;
                            const types = Array.from(e?.dataTransfer?.types ?? []);
                            if (!types.includes('Files')) return;
                            e.preventDefault();
                            e.stopPropagation();
                            if (!globalDragging) setGlobalDragging(true);
                        } catch (_) { }
                    }} onDragLeave={e => {
                        try {
                            if (isUploading) return;
                            const types = Array.from(e?.dataTransfer?.types ?? []);
                            if (!types.includes('Files')) return;
                            e.preventDefault();
                            e.stopPropagation();
                            if (!e.currentTarget.contains(e.relatedTarget)) setGlobalDragging(false);
                        } catch (_) { }
                    }} onDrop={e => {
                        try {
                            if (isUploading || attachedMedia.length >= MAX_MEDIA) {
                                e.preventDefault();
                                e.stopPropagation();
                                return;
                            }
                            const files = Array.from(e?.dataTransfer?.files ?? []);
                            if (!files || files.length === 0) return;
                            e.preventDefault();
                            e.stopPropagation();
                            setGlobalDragging(false);
                            if (editorUpload && typeof editorUpload.uploadFile === 'function') {
                                editorUpload.uploadFile(files[0]);
                            }
                        } catch (_) { }
                    }}>
                        <form id="create-post-form" onSubmit={handleSubmit} autoComplete="off" onKeyDown={e => {
                            if (e.key !== 'Tab') return;
                            const form = e.currentTarget;
                            const focusable = form.querySelectorAll('input:not([type="hidden"]):not([tabindex="-1"]):not(:disabled), textarea:not(:disabled), button[type="submit"]:not(:disabled)');
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
                        }}>
                            {isEditMode && <Row>
                                <Label>Tx Hash:</Label>
                                <ValueBox>
                                    <Mono>{overrideId}</Mono>
                                </ValueBox>
                            </Row>}
                            <Row>
                                <Label>Topic:</Label>
                                <div>
                                    <TopicSelector value={topicValue} maxLength={limits.maxTopic} minLength={limits.minTopic} onChange={handleTopicChange} disabled={isSubmitting} aria-label="Topic" />
                                    <HelpText>
                                        Topics are communities centered around specific interests. Posting in the wrong topic may affect your overall trust status on Mirage. <b>Make sure to post into the right category!</b>
                                    </HelpText>
                                </div>
                            </Row>
                            <Row>
                                <Label>Title:</Label>
                                <div style={{
                                    display: 'flex',
                                    flexDirection: 'column'
                                }}>
                                    <StyledInputBox ref={titleInputRef} name="title" id="title" value={titleValue} placeholder="Title of your post" onPaste={handleTitlePaste} autoComplete="off" autoCorrect="on" autoCapitalize="sentences" spellCheck={true} maxLength={limits.maxTitle} onChange={handleTitleChange} disabled={isSubmitting} aria-label="Title" onKeyDown={e => {
                                        if (e.key === 'Enter') {
                                            e.preventDefault();
                                            if (contentEditorRef.current) contentEditorRef.current.focus();
                                        }
                                    }} />
                                    {!isSubmitting && <CharCounter $warn={getByteLength(titleValue) >= limits.maxTitle}>
                                        {getByteLength(titleValue)} / {limits.maxTitle} {limits.willPayFee ? '(paid tier)' : '(free tier)'}
                                    </CharCounter>}
                                </div>
                            </Row>
                            <Row style={{
                                alignItems: 'flex-start'
                            }}>
                                <Label style={{
                                    paddingTop: '1px'
                                }}>Tag:</Label>
                                <div style={{
                                    display: 'flex',
                                    flexDirection: 'column',
                                    gap: '0.35rem'
                                }}>
                                    <TagToggle>
                                        <input type="checkbox" tabIndex={-1} checked={tagEnabled} onChange={e => {
                                            const enabled = e.target.checked;
                                            setTagEnabled(enabled);
                                            if (enabled) {
                                                setTagValue(prev => prev || TAG_OPTIONS_ENABLED[0]?.value || 'sensitive');
                                                setTagManuallySet(true);
                                            } else {
                                                setTagValue('');
                                                setTagManuallySet(true);
                                            }
                                            if (submitError) setSubmitError('');
                                        }} disabled={isSubmitting} aria-label="Add content warning" />
                                        Add content warning
                                    </TagToggle>
                                    {tagEnabled && <>
                                        <StyledSelect tabIndex={-1} value={tagValue} onChange={e => {
                                            setTagValue(e.target.value);
                                            setTagManuallySet(true);
                                            if (submitError) setSubmitError('');
                                        }} disabled={isSubmitting} aria-label="Content tag">
                                            {TAG_OPTIONS_ENABLED.map(opt => <option key={opt.value || 'none'} value={opt.value}>{opt.label}</option>)}
                                        </StyledSelect>
                                        <HelpText>
                                            Optional content warning. Choose a tag if the post contains sensitive material.
                                        </HelpText>
                                    </>}
                                </div>
                            </Row>
                            <Row>
                                <Label>Media:</Label>
                                <MediaRow>
                                    <StickerPicker onSelect={stickerUrl => {
                                        if (attachedMedia.length >= MAX_MEDIA) return;
                                        addMediaItem('image', stickerUrl);
                                    }} disabled={isSubmitting || isUploading || attachedMedia.length >= MAX_MEDIA} />
                                    <GifPicker onSelect={gifUrl => {
                                        if (attachedMedia.length >= MAX_MEDIA) return;
                                        addMediaItem('image', gifUrl);
                                    }} disabled={isSubmitting || isUploading || attachedMedia.length >= MAX_MEDIA} />
                                    <MediaIconButton type="button" tabIndex={-1} onClick={() => {
                                        try {
                                            editorUpload && editorUpload.selectFile();
                                        } catch (_) { }
                                    }} disabled={isSubmitting || isUploading || attachedMedia.length >= MAX_MEDIA} aria-label="Upload" title="Upload">
                                        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                                            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                                            <polyline points="17 8 12 3 7 8" />
                                            <line x1="12" y1="3" x2="12" y2="15" />
                                        </svg>
                                    </MediaIconButton>
                                    {attachedMedia.length > 0 && <span style={{
                                        fontSize: '0.65rem',
                                        color: '#888'
                                    }}>
                                        {attachedMedia.length}/{MAX_MEDIA}
                                    </span>}
                                    {attachedMedia.map((item, idx) => <MediaPreviewWrapper key={`${item.url}-${idx}`}>
                                        <MediaPreviewImage src={item.type === 'image' ? item.url : getVideoThumbnailUrl(item.url) || item.url} alt="" onLoad={() => {
                                            setThumbsLoading(prev => {
                                                const n = new Set(prev);
                                                n.delete(item.url);
                                                return n;
                                            });
                                        }} onError={() => {
                                            setThumbsLoading(prev => {
                                                const n = new Set(prev);
                                                n.delete(item.url);
                                                return n;
                                            });
                                        }} />
                                        {thumbsLoading.has(item.url) && <MediaSpinner />}
                                        <MediaRemoveButton type="button" tabIndex={-1} disabled={isSubmitting} onClick={() => {
                                            if (isSubmitting) return;
                                            setAttachedMedia(prev => prev.filter((_, i) => i !== idx));
                                        }} aria-label="Remove attached media" title="Remove attached media">
                                            ×
                                        </MediaRemoveButton>
                                    </MediaPreviewWrapper>)}
                                    {isUploading && <MediaPreviewWrapper>
                                        <div style={{
                                            width: '100%',
                                            height: '100%',
                                            display: 'flex',
                                            flexDirection: 'column',
                                            alignItems: 'center',
                                            justifyContent: 'center',
                                            padding: '0.5rem',
                                            boxSizing: 'border-box'
                                        }}>
                                            <span style={{
                                                fontSize: '0.7rem',
                                                color: '#888',
                                                marginBottom: '0.25rem'
                                            }}>
                                                Uploading {uploadProgress !== null ? `${Math.round(uploadProgress)}%` : '...'}
                                            </span>
                                            <Button variant="danger" size="xs" tabIndex={-1} onClick={() => {
                                                try {
                                                    if (editorUpload && editorUpload.cancelUpload) {
                                                        editorUpload.cancelUpload();
                                                    }
                                                } catch (_) { }
                                            }}>
                                                Cancel
                                            </Button>
                                        </div>
                                    </MediaPreviewWrapper>}
                                </MediaRow>
                            </Row>
                            <Row>
                                <Label>Content:</Label>
                                <div style={{
                                    display: 'flex',
                                    flexDirection: 'column'
                                }}>
                                    <MarkdownEditor value={contentValue} onChange={v => {
                                        setContentValue(v);
                                    }} maxLength={limits.maxContent} disabled={isSubmitting} uploadBlocked={attachedMedia.length >= MAX_MEDIA} onSubmitShortcut={() => {
                                        try {
                                            const form = document.getElementById('create-post-form');
                                            if (form) form.requestSubmit();
                                        } catch (_) { }
                                    }} showCounters={false} renderHelperRow={false} toolbarButtonSize="1.5rem" toolbarIconSize="0.95rem" minHeight="10rem" registerUploadHandler={setEditorUpload} editorRef={ref => {
                                        contentEditorRef.current = ref;
                                    }} belowElement={submitError ? <ErrorMessage role="alert">{submitError}</ErrorMessage> : null} onMediaUploaded={(type, url, error) => {
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
                                    }} onUploadStateChange={uploading => {
                                        setIsUploading(uploading);
                                        if (!uploading) {
                                            setUploadProgress(null);
                                        }
                                    }} onUploadProgress={progress => {
                                        setUploadProgress(progress);
                                    }} suffixLabel={limits.willPayFee ? '(paid tier)' : '(free tier)'} />
                                    <ContentActionsRow>
                                        <div style={{
                                            display: 'flex',
                                            flexDirection: 'column',
                                            gap: '2px',
                                            minWidth: 0,
                                            flex: '1 1 auto',
                                            alignSelf: 'flex-start'
                                        }}>
                                            <ContentCounter $warn={contentValue.length >= limits.maxContent}>
                                                {contentValue.length} / {limits.maxContent} {limits.willPayFee ? '(paid tier)' : '(free tier)'}
                                            </ContentCounter>
                                        </div>
                                        <div style={{
                                            display: 'flex',
                                            alignItems: 'center',
                                            gap: '0.5rem'
                                        }}>
                                            <Button type="submit" disabled={isSubmitting || isUploading} loading={isSubmitting} mobileFullWidth>
                                                {isSubmitting ? submitStatus === 'verifying' ? 'Verifying...' : submitStatus === 'submitting' ? 'Submitting...' : 'Processing' : isEditMode ? 'Save Edit' : 'Submit'}
                                            </Button>
                                        </div>
                                    </ContentActionsRow>
                                </div>
                            </Row>
                        </form>
                        {globalDragging && <GlobalDropOverlay>Drop image/video to upload</GlobalDropOverlay>}
                    </ContainerBody>
                </TabbedContainer>
            </ModernPostFeed>
        </CappedPageColumn>
    </ContentGrid>;
}
export default CreatePostView;