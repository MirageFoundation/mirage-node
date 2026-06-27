import { uploadToNode } from './ImageUpload';

/**
 * Read duration + dimensions from a video file in-browser. These are sent to
 * the node so it can enforce the video resolution policy (the node has no
 * transcoder on the default local provider).
 */
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
        video.onerror = () => reject(new Error('Invalid video file'));
        video.src = window.URL.createObjectURL(file);
    });
}

function appendDimensionsToUrl(url, width, height) {
    if (!width || !height) return url;
    const sep = url.includes('?') ? '&' : '?';
    return `${url}${sep}w=${width}&h=${height}`;
}

/**
 * Upload a video to the node with cancellation support.
 * The node enforces duration/resolution policy and returns the playable URL.
 * @param {File} file
 * @param {(progress:number)=>void} [onProgress]
 * @param {{current: XMLHttpRequest|null}} [xhrRef]
 * @returns {Promise<string>} final video URL
 */
export async function uploadVideoWithCancel(file, onProgress, xhrRef) {
    try {
        const meta = await getVideoMeta(file);
        const fields = {
            duration: Math.round(meta.duration || 0),
            width: meta.width,
            height: meta.height,
        };
        const url = await uploadToNode(file, 'video', fields, onProgress, xhrRef);
        return appendDimensionsToUrl(url, meta.width, meta.height);
    } catch (e) {
        if (e && e.message === 'Upload aborted') throw e;
        console.error('[VideoUpload] Upload error:', e);
        throw e;
    }
}

/**
 * High-level upload without external cancellation handle.
 * @param {File} file
 * @param {(progress:number)=>void} [onProgress]
 * @returns {Promise<string>}
 */
export async function uploadVideo(file, onProgress) {
    return uploadVideoWithCancel(file, onProgress, { current: null });
}
