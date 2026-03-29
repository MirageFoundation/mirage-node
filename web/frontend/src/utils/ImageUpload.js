import Api from './api';

function assertAllowedUploadUrl(uploadUrl) {
    let parsed;
    try {
        parsed = new URL(String(uploadUrl || ''));
    } catch (_) {
        throw new Error('Invalid upload URL');
    }
    const host = parsed.hostname.toLowerCase();
    const isAllowedHost = host.endsWith('imagedelivery.net');
    if (parsed.protocol !== 'https:' || !isAllowedHost) {
        throw new Error('Upload URL host is not allowed');
    }
}

/**
 * Downscale an image to a maximum size while maintaining aspect ratio
 * @param {File} file - The image file to downscale
 * @param {number} maxWidth - Maximum width in pixels (default: 3840)
 * @param {number} maxHeight - Maximum height in pixels (default: 2160)
 * @returns {Promise<File>} - A Promise that resolves to a new File object with the downscaled image
 */
export async function downscaleImage(file, maxWidth = 3840, maxHeight = 2160) {
    return new Promise((resolve, reject) => {
        const reader = new FileReader();
        
        reader.onload = (e) => {
            const img = new Image();
            
            img.onload = () => {
                let width = img.width;
                let height = img.height;
                
                // Calculate new dimensions maintaining aspect ratio
                if (width > maxWidth || height > maxHeight) {
                    const ratio = Math.min(maxWidth / width, maxHeight / height);
                    width = Math.round(width * ratio);
                    height = Math.round(height * ratio);
                }
                
                // Create canvas and draw resized image
                const canvas = document.createElement('canvas');
                canvas.width = width;
                canvas.height = height;
                const ctx = canvas.getContext('2d');
                
                if (!ctx) {
                    reject(new Error('Could not get canvas context'));
                    return;
                }
                
                ctx.drawImage(img, 0, 0, width, height);
                
                // Convert to blob, prefer WebP, fallback to JPEG
                canvas.toBlob((blob) => {
                    if (!blob) {
                        reject(new Error('Failed to create blob from canvas'));
                        return;
                    }
                    
                    // Determine file extension - preserve original extension if possible
                    const originalName = file.name || 'image';
                    const nameWithoutExt = originalName.replace(/\.[^/.]+$/, '');
                    // Extract original extension or infer from file type
                    let extension = '';
                    if (originalName.includes('.')) {
                        const lastDot = originalName.lastIndexOf('.');
                        if (lastDot > 0 && lastDot < originalName.length - 1) {
                            extension = originalName.substring(lastDot).toLowerCase();
                        }
                    }
                    // If no extension found, infer from file type
                    if (!extension) {
                        if (file.type && file.type.includes('png')) {
                            extension = '.png';
                        } else if (file.type && file.type.includes('gif')) {
                            extension = '.gif';
                        } else if (file.type && file.type.includes('webp')) {
                            extension = '.webp';
                        } else {
                            extension = '.jpg'; // Default to jpg
                        }
                    }
                    const newFileName = `${nameWithoutExt}${extension}`;
                    
                    // Create new File object with preserved extension
                    const newFile = new File([blob], newFileName, {
                        type: blob.type || 'image/jpeg',
                        lastModified: Date.now()
                    });
                    
                    resolve(newFile);
                }, 'image/jpeg', 0.92);
            };
            
            img.onerror = () => {
                reject(new Error('Failed to load image'));
            };
            
            img.src = e.target.result;
        };
        
        reader.onerror = () => {
            reject(new Error('Failed to read file'));
        };
        
        reader.readAsDataURL(file);
    });
}

/**
 * Get an upload URL from the backend for Cloudflare direct upload
 * @param {string} type - The type of upload ('image' or 'video')
 * @returns {Promise<{uploadURL: string, id: string}>} - A Promise that resolves to upload URL and ID
 */
export async function getUploadUrl(type = 'image') {
    try {
        const response = await Api.post('get_upload_url', { type }, { timeoutMs: 15000 });
        
        if (response.error) {
            throw new Error(response.error);
        }
        
        if (!response.uploadURL || !response.id || !response.accountHash) {
            throw new Error('Invalid response from server');
        }
        
        return {
            uploadURL: response.uploadURL,
            id: response.id,
            accountHash: response.accountHash
        };
    } catch (error) {
        throw new Error(`Failed to get upload URL: ${error.message}`);
    }
}

/**
 * Upload a file directly to Cloudflare using the provided upload URL
 * @param {File} file - The file to upload
 * @param {string} uploadUrl - The Cloudflare direct upload URL
 * @param {string} accountHash - The Cloudflare account hash for image delivery URL
 * @param {Function} onProgress - Optional progress callback (progress: number) => void
 * @returns {Promise<string>} - A Promise that resolves to the final image URL
 */
export async function uploadToCloudflare(file, uploadUrl, accountHash, onProgress, originalExtension = '') {
    return new Promise((resolve, reject) => {
        try {
            assertAllowedUploadUrl(uploadUrl);
        } catch (e) {
            reject(e);
            return;
        }
        const xhr = new XMLHttpRequest();
        
        xhr.upload.addEventListener('progress', (e) => {
            if (e.lengthComputable && onProgress) {
                const progress = (e.loaded / e.total) * 100;
                onProgress(progress);
            }
        });
        
        xhr.addEventListener('load', () => {
            if (xhr.status >= 200 && xhr.status < 300) {
                try {
                    const response = JSON.parse(xhr.responseText);
                    
                    // Cloudflare Images returns the image URL in different formats
                    // Check for common response formats
                    let imageUrl = null;
                    
                    if (response.result && response.result.variants && response.result.variants.length > 0) {
                        // New format: variants array
                        imageUrl = response.result.variants[0];
                    } else if (response.result && response.result.id) {
                        // Format with ID - construct URL with account hash
                        // NOTE: Cloudflare Images doesn't support file extensions in the URL path
                        // The /public endpoint serves images regardless of format
                        // We append the extension as a query parameter for clarity/display purposes
                        const id = response.result.id;
                        // Use original extension if provided, otherwise extract from file name
                        let extension = originalExtension || '';
                        if (!extension) {
                            const fileName = file.name || '';
                            if (fileName && fileName.includes('.')) {
                                const lastDot = fileName.lastIndexOf('.');
                                if (lastDot > 0 && lastDot < fileName.length - 1) {
                                    extension = fileName.substring(lastDot).toLowerCase();
                                }
                            }
                        }
                        // If still no extension found, try to infer from file type
                        if (!extension && file.type) {
                            if (file.type.includes('png')) {
                                extension = '.png';
                            } else if (file.type.includes('gif')) {
                                extension = '.gif';
                            } else if (file.type.includes('webp')) {
                                extension = '.webp';
                            } else {
                                extension = '.jpg'; // Default to jpg for JPEG images
                            }
                        }
                        // Ensure extension starts with dot
                        if (extension && !extension.startsWith('.')) {
                            extension = '.' + extension;
                        }
                        // Use canonical Cloudflare Images URL without a file extension in the path
                        imageUrl = `https://imagedelivery.net/${accountHash}/${id}/public`;
                    } else if (response.variants && response.variants.length > 0) {
                        // Direct variants
                        imageUrl = response.variants[0];
                    } else if (response.url) {
                        imageUrl = response.url;
                    } else if (typeof response === 'string') {
                        // Sometimes it's just a string URL
                        imageUrl = response;
                    }
                    
                    if (!imageUrl) {
                        // Fallback: try to extract from response text
                        const text = xhr.responseText;
                        const urlMatch = text.match(/https?:\/\/[^\s"']+/);
                        if (urlMatch) {
                            imageUrl = urlMatch[0];
                        }
                    }
                    
                    if (!imageUrl) {
                        reject(new Error('Could not determine image URL from Cloudflare response'));
                        return;
                    }
                    
                    resolve(imageUrl);
                } catch (error) {
                    reject(new Error(`Failed to parse Cloudflare response: ${error.message}`));
                }
            } else {
                let errorMsg = `Upload failed with status ${xhr.status}`;
                try {
                    const errorResponse = JSON.parse(xhr.responseText);
                    if (errorResponse.errors && errorResponse.errors.length > 0) {
                        errorMsg = errorResponse.errors[0].message || errorMsg;
                    }
                } catch (_) {
                    // Ignore parse errors
                }
                reject(new Error(errorMsg));
            }
        });
        
        xhr.addEventListener('error', () => {
            reject(new Error('Network error during upload'));
        });
        
        xhr.addEventListener('abort', () => {
            reject(new Error('Upload aborted'));
        });
        
        xhr.open('POST', uploadUrl);
        
        // Cloudflare direct upload expects the file as FormData
        const formData = new FormData();
        formData.append('file', file);
        
        xhr.send(formData);
    });
}

/**
 * Complete image upload flow: downscale → get URL → upload → return final image URL
 * @param {File} file - The image file to upload
 * @param {Function} onProgress - Optional progress callback (progress: number) => void
 * @returns {Promise<string>} - A Promise that resolves to the final image URL
 */
export async function uploadImage(file, onProgress) {
    try {
        // Extract original file extension BEFORE downscaling
        const originalFileName = file.name || '';
        let originalExtension = '';
        if (originalFileName.includes('.')) {
            const lastDot = originalFileName.lastIndexOf('.');
            if (lastDot > 0 && lastDot < originalFileName.length - 1) {
                originalExtension = originalFileName.substring(lastDot).toLowerCase();
            }
        }
        // Fallback to file type if no extension in name
        if (!originalExtension) {
            if (file.type && file.type.includes('png')) {
                originalExtension = '.png';
            } else if (file.type && file.type.includes('gif')) {
                originalExtension = '.gif';
            } else if (file.type && file.type.includes('webp')) {
                originalExtension = '.webp';
            } else {
                originalExtension = '.jpg';
            }
        }
        
        // Step 1: Downscale image to 4K max
        const downscaledFile = await downscaleImage(file);
        
        // Step 2: Get upload URL from backend
        const { uploadURL, accountHash } = await getUploadUrl('image');
        
        // Step 3: Upload to Cloudflare - pass original extension explicitly
        const imageUrl = await uploadToCloudflare(downscaledFile, uploadURL, accountHash, onProgress, originalExtension);
        
        return imageUrl;
    } catch (error) {
        throw new Error(`Image upload failed: ${error.message}`);
    }
}

