import Api from '../lib/api';

/**
 * Get a Stream direct upload URL
 */
export async function getUploadUrlVideo() {
    const response = await Api.post('get_upload_url', { type: 'video' }, { timeoutMs: 20000 });
    if (!response || !response.uploadURL) {
        throw new Error('Invalid response from server (video)');
    }
    return {
        uploadURL: response.uploadURL,
        provider: response.provider || 'stream',
        uid: response.uid || '',
    };
}

/**
 * Upload to Cloudflare Stream direct upload URL
 * Returns the video UID from the Stream API response
 */
export async function uploadToStreamCancellable(file, uploadUrl, onProgress, xhrRef) {
    return new Promise((resolve, reject) => {
        const xhr = new XMLHttpRequest();
        if (xhrRef) {
            try { xhrRef.current = xhr; } catch (_) { }
        }
        if (onProgress && xhr.upload) {
            xhr.upload.addEventListener('progress', (e) => {
                if (e.lengthComputable) onProgress((e.loaded / e.total) * 100);
            });
        }
        xhr.addEventListener('load', () => {
            if (xhrRef) {
                try { xhrRef.current = null; } catch (_) { }
            }
            if (xhr.status >= 200 && xhr.status < 300) {
                try {
                    // Try to parse a uid/id from Stream response when available
                    const responseText = xhr.responseText || '{}';
                    const json = JSON.parse(responseText);
                    const result = json && json.result ? json.result : {};
                    const uid = result.uid || result.id || json.uid || json.id || null;
                    resolve(uid || true);
                } catch (e) {
                    console.warn('[VideoUpload] Could not parse upload response:', e, xhr.responseText);
                    // Some responses are empty; resolve success and let caller fall back
                    resolve(true);
                }
            } else {
                try {
                    const err = JSON.parse(xhr.responseText || '{}');
                    const msg = (err && err.errors && err.errors[0] && err.errors[0].message) || `HTTP ${xhr.status}`;
                    console.error('[VideoUpload] Upload failed:', xhr.status, msg, xhr.responseText);
                    reject(new Error(msg));
                } catch (_) {
                    console.error('[VideoUpload] Upload failed:', xhr.status, xhr.responseText);
                    reject(new Error(`HTTP ${xhr.status}`));
                }
            }
        });
        xhr.addEventListener('error', () => {
            if (xhrRef) {
                try { xhrRef.current = null; } catch (_) { }
            }
            reject(new Error('Network error during upload'));
        });
        xhr.addEventListener('abort', () => {
            if (xhrRef) {
                try { xhrRef.current = null; } catch (_) { }
            }
            reject(new Error('Upload aborted'));
        });
        xhr.open('POST', uploadUrl);
        const formData = new FormData();
        formData.append('file', file);
        xhr.send(formData);
    });
}

function getVideoMeta(file) {
    return new Promise((resolve, reject) => {
        const video = document.createElement('video');
        video.preload = 'metadata';
        video.onloadedmetadata = () => {
            const duration = video.duration;
            const width = video.videoWidth || 0;
            const height = video.videoHeight || 0;
            window.URL.revokeObjectURL(video.src);
            resolve({ duration, width, height });
        };
        video.onerror = () => {
            reject(new Error('Invalid video file'));
        };
        video.src = window.URL.createObjectURL(file);
    });
}

function appendDimensionsToUrl(url, width, height) {
    if (!width || !height) return url;
    const sep = url.includes('?') ? '&' : '?';
    return `${url}${sep}w=${width}&h=${height}`;
}

/**
 * High-level: upload a video file to Stream and return an embeddable iframe URL
 */
export async function uploadVideo(file, onProgress) {
    const meta = await getVideoMeta(file);
    if (meta.duration > 60) {
        throw new Error(`Video is too long (${Math.round(meta.duration)}s). Maximum allowed duration is 60 seconds.`);
    }
    const { uploadURL, uid } = await getUploadUrlVideo();
    const returnedUid = await uploadToStreamCancellable(file, uploadURL, onProgress);
    const finalUid = (typeof returnedUid === 'string' && returnedUid) ? returnedUid : uid;
    if (!finalUid) {
        throw new Error('Could not determine video UID from upload response');
    }
    return appendDimensionsToUrl(`https://videodelivery.net/${finalUid}/manifest/video.m3u8`, meta.width, meta.height);
}

/**
 * High-level with cancellation support
 */
export async function uploadVideoWithCancel(file, onProgress, xhrRef) {
    try {
        const meta = await getVideoMeta(file);
        if (meta.duration > 60) {
            throw new Error(`Video is too long (${Math.round(meta.duration)}s). Maximum allowed duration is 60 seconds.`);
        }
        const { uploadURL, uid } = await getUploadUrlVideo();
        const returnedUid = await uploadToStreamCancellable(file, uploadURL, onProgress, xhrRef);
        const finalUid = (typeof returnedUid === 'string' && returnedUid) ? returnedUid : uid;
        if (!finalUid) {
            throw new Error('Could not determine video UID from upload response');
        }
        return appendDimensionsToUrl(`https://videodelivery.net/${finalUid}/manifest/video.m3u8`, meta.width, meta.height);
    } catch (e) {
        console.error('[VideoUpload] Upload error:', e);
        throw e;
    }
}

