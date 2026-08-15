import Api from './api';

/**
 * Uniform, provider-agnostic upload to this node.
 * Always POSTs multipart to /api/upload_media and returns the finished URL.
 * The node hides all provider specifics (local disk / Cloudflare / Bunny).
 *
 * @param {File|Blob} file
 * @param {'image'|'video'} kind
 * @param {Record<string, any>} fields - extra form fields (e.g. duration/height for video)
 * @param {(progress:number)=>void} [onProgress]
 * @param {{current: XMLHttpRequest|null}} [xhrRef] - for cancellation
 * @returns {Promise<string>} the final media URL
 */
export function uploadToNode(file, kind, fields, onProgress, xhrRef) {
    return new Promise((resolve, reject) => {
        const xhr = new XMLHttpRequest();
        if (xhrRef) { try { xhrRef.current = xhr; } catch (_) { } }

        if (onProgress && xhr.upload) {
            xhr.upload.addEventListener('progress', (e) => {
                if (e.lengthComputable) onProgress((e.loaded / e.total) * 100);
            });
        }

        const clearRef = () => { if (xhrRef) { try { xhrRef.current = null; } catch (_) { } } };

        xhr.addEventListener('load', () => {
            clearRef();
            if (xhr.status >= 200 && xhr.status < 300) {
                try {
                    const json = JSON.parse(xhr.responseText || '{}');
                    if (json && json.url) {
                        resolve(json.url);
                    } else {
                        reject(new Error((json && json.error) ? json.error : 'Upload failed: no URL returned'));
                    }
                } catch (e) {
                    reject(new Error('Failed to parse upload response'));
                }
            } else {
                let msg = `Upload failed with status ${xhr.status}`;
                try {
                    const j = JSON.parse(xhr.responseText || '{}');
                    if (j && j.error) msg = j.error;
                } catch (_) { }
                reject(new Error(msg));
            }
        });
        xhr.addEventListener('error', () => { clearRef(); reject(new Error('Network error during upload')); });
        xhr.addEventListener('abort', () => { clearRef(); reject(new Error('Upload aborted')); });

        // kind goes in the query string: the node needs it to pick the per-kind
        // size cap *before* it parses the multipart body, and reading a form field
        // is what forces that parse. It stays in the form body too so the request
        // is still well-formed for a node that has not been updated yet.
        xhr.open('POST', Api.buildUrl('upload_media', { kind }));
        const fd = new FormData();
        fd.append('kind', kind);
        fd.append('file', file);
        if (fields && typeof fields === 'object') {
            Object.entries(fields).forEach(([k, v]) => {
                if (v !== undefined && v !== null) fd.append(k, String(v));
            });
        }
        xhr.send(fd);
    });
}

/**
 * Downscale an image to a maximum size while maintaining aspect ratio.
 * @param {File} file - The image file to downscale
 * @param {number} maxWidth - Maximum width in pixels (default: 3840)
 * @param {number} maxHeight - Maximum height in pixels (default: 2160)
 * @returns {Promise<File>} - A Promise that resolves to a new downscaled File
 */
export async function downscaleImage(file, maxWidth = 3840, maxHeight = 2160) {
    return new Promise((resolve, reject) => {
        const reader = new FileReader();

        reader.onload = (e) => {
            const img = new Image();

            img.onload = () => {
                let width = img.width;
                let height = img.height;

                if (width > maxWidth || height > maxHeight) {
                    const ratio = Math.min(maxWidth / width, maxHeight / height);
                    width = Math.round(width * ratio);
                    height = Math.round(height * ratio);
                }

                const canvas = document.createElement('canvas');
                canvas.width = width;
                canvas.height = height;
                const ctx = canvas.getContext('2d');

                if (!ctx) {
                    reject(new Error('Could not get canvas context'));
                    return;
                }

                ctx.drawImage(img, 0, 0, width, height);

                canvas.toBlob((blob) => {
                    if (!blob) {
                        reject(new Error('Failed to create blob from canvas'));
                        return;
                    }
                    const originalName = file.name || 'image';
                    const nameWithoutExt = originalName.replace(/\.[^/.]+$/, '');
                    const newFile = new File([blob], `${nameWithoutExt}.jpg`, {
                        type: blob.type || 'image/jpeg',
                        lastModified: Date.now(),
                    });
                    resolve(newFile);
                }, 'image/jpeg', 0.92);
            };

            img.onerror = () => reject(new Error('Failed to load image'));
            img.src = e.target.result;
        };

        reader.onerror = () => reject(new Error('Failed to read file'));
        reader.readAsDataURL(file);
    });
}

/**
 * Upload an image with cancellation support: downscale then POST to the node.
 * @param {File} file
 * @param {(progress:number)=>void} [onProgress]
 * @param {{current: XMLHttpRequest|null}} [xhrRef]
 * @returns {Promise<string>} final image URL
 */
export async function uploadImageWithCancel(file, onProgress, xhrRef) {
    try {
        const downscaled = await downscaleImage(file);
        return await uploadToNode(downscaled, 'image', {}, onProgress, xhrRef);
    } catch (error) {
        if (xhrRef) { try { xhrRef.current = null; } catch (_) { } }
        if (error && error.message === 'Upload aborted') throw error;
        throw new Error(`Image upload failed: ${error.message}`);
    }
}

/**
 * Complete image upload flow: downscale -> upload -> return final URL.
 * @param {File} file
 * @param {(progress:number)=>void} [onProgress]
 * @returns {Promise<string>}
 */
export async function uploadImage(file, onProgress) {
    return uploadImageWithCancel(file, onProgress, { current: null });
}
