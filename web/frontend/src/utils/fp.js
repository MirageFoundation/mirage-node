/**
 * Device fingerprint collection for fraud detection.
 * Collects 50+ browser/device characteristics and sends to backend.
 * 
 * The power of fingerprinting is in COMBINATIONS: individual attributes
 * may be common, but the combination of all attributes is unique.
 * 
 * Note: This code is minified in production builds, so variable names
 * are not visible to end users. Only the API endpoint (/api/core/fp) is visible.
 */

import Api from '../lib/api';

async function computeSha256Hash(str) {
    if (!str) return null;
    try {
        const encoder = new TextEncoder();
        const data = encoder.encode(str);
        const hashBuffer = await crypto.subtle.digest('SHA-256', data);
        const hashArray = Array.from(new Uint8Array(hashBuffer));
        return hashArray.map(b => b.toString(16).padStart(2, '0')).join('').slice(0, 32);
    } catch (e) {
        return null;
    }
}

function getCanvasFingerprint() {
    try {
        const canvas = document.createElement('canvas');
        canvas.width = 200;
        canvas.height = 50;
        const ctx = canvas.getContext('2d');
        if (!ctx) return null;

        ctx.textBaseline = 'top';
        ctx.font = '14px Arial';
        ctx.fillStyle = '#f60';
        ctx.fillRect(125, 1, 62, 20);
        ctx.fillStyle = '#069';
        ctx.fillText('Mirage', 2, 15);
        ctx.fillStyle = 'rgba(102, 204, 0, 0.7)';
        ctx.fillText('Mirage', 4, 17);

        return canvas.toDataURL();
    } catch (e) {
        return null;
    }
}

function getWebGLInfo() {
    try {
        const canvas = document.createElement('canvas');
        const gl = canvas.getContext('webgl') || canvas.getContext('experimental-webgl');
        if (!gl) return { vendor: null, renderer: null, extensions: null, params: null };

        const debugInfo = gl.getExtension('WEBGL_debug_renderer_info');
        const vendor = debugInfo ? gl.getParameter(debugInfo.UNMASKED_VENDOR_WEBGL) : null;
        const renderer = debugInfo ? gl.getParameter(debugInfo.UNMASKED_RENDERER_WEBGL) : null;

        // Get all supported extensions
        const extensions = gl.getSupportedExtensions() || [];

        // Get key WebGL parameters
        const params = {
            maxTextureSize: gl.getParameter(gl.MAX_TEXTURE_SIZE),
            maxVertexAttribs: gl.getParameter(gl.MAX_VERTEX_ATTRIBS),
            maxVertexUniformVectors: gl.getParameter(gl.MAX_VERTEX_UNIFORM_VECTORS),
            maxFragmentUniformVectors: gl.getParameter(gl.MAX_FRAGMENT_UNIFORM_VECTORS),
            maxVaryingVectors: gl.getParameter(gl.MAX_VARYING_VECTORS),
            maxCombinedTextureImageUnits: gl.getParameter(gl.MAX_COMBINED_TEXTURE_IMAGE_UNITS),
            maxTextureImageUnits: gl.getParameter(gl.MAX_TEXTURE_IMAGE_UNITS),
            maxVertexTextureImageUnits: gl.getParameter(gl.MAX_VERTEX_TEXTURE_IMAGE_UNITS),
            maxRenderbufferSize: gl.getParameter(gl.MAX_RENDERBUFFER_SIZE),
            maxViewportDims: Array.from(gl.getParameter(gl.MAX_VIEWPORT_DIMS) || []),
            aliasedLineWidthRange: Array.from(gl.getParameter(gl.ALIASED_LINE_WIDTH_RANGE) || []),
            aliasedPointSizeRange: Array.from(gl.getParameter(gl.ALIASED_POINT_SIZE_RANGE) || []),
            renderer: gl.getParameter(gl.RENDERER),
            vendor: gl.getParameter(gl.VENDOR),
            version: gl.getParameter(gl.VERSION),
            shadingLanguageVersion: gl.getParameter(gl.SHADING_LANGUAGE_VERSION),
        };

        return { vendor, renderer, extensions, params };
    } catch (e) {
        return { vendor: null, renderer: null, extensions: null, params: null };
    }
}

function getPluginsInfo() {
    try {
        if (!navigator.plugins || navigator.plugins.length === 0) {
            return { list: [], count: 0 };
        }
        const list = [];
        for (let i = 0; i < navigator.plugins.length; i++) {
            const p = navigator.plugins[i];
            list.push({
                name: p.name || '',
                description: p.description || '',
                filename: p.filename || '',
            });
        }
        return { list, count: list.length };
    } catch (e) {
        return { list: [], count: 0 };
    }
}

function getMimeTypesInfo() {
    try {
        if (!navigator.mimeTypes || navigator.mimeTypes.length === 0) {
            return { list: [], count: 0 };
        }
        const list = [];
        for (let i = 0; i < navigator.mimeTypes.length; i++) {
            const m = navigator.mimeTypes[i];
            list.push({
                type: m.type || '',
                description: m.description || '',
                suffixes: m.suffixes || '',
            });
        }
        return { list, count: list.length };
    } catch (e) {
        return { list: [], count: 0 };
    }
}

function getAudioInfo() {
    try {
        const audioCtx = new (window.AudioContext || window.webkitAudioContext)();
        const sampleRate = audioCtx.sampleRate;

        // Get destination properties
        const dest = audioCtx.destination;
        const destination = {
            channelCount: dest.channelCount,
            maxChannelCount: dest.maxChannelCount,
            channelCountMode: dest.channelCountMode,
            channelInterpretation: dest.channelInterpretation,
        };

        // Check supported audio codecs
        const audio = document.createElement('audio');
        const codecs = {
            mp3: audio.canPlayType('audio/mpeg'),
            mp4: audio.canPlayType('audio/mp4; codecs="mp4a.40.2"'),
            aac: audio.canPlayType('audio/aac'),
            ogg: audio.canPlayType('audio/ogg; codecs="vorbis"'),
            opus: audio.canPlayType('audio/ogg; codecs="opus"'),
            wav: audio.canPlayType('audio/wav; codecs="1"'),
            flac: audio.canPlayType('audio/flac'),
            webm: audio.canPlayType('audio/webm; codecs="opus"'),
        };

        audioCtx.close().catch(() => {});

        return { sampleRate, destination, codecs };
    } catch (e) {
        return { sampleRate: null, destination: null, codecs: null };
    }
}

function getVideoInfo() {
    try {
        const video = document.createElement('video');
        const codecs = {
            mp4_h264: video.canPlayType('video/mp4; codecs="avc1.42E01E"'),
            mp4_h265: video.canPlayType('video/mp4; codecs="hvc1"'),
            webm_vp8: video.canPlayType('video/webm; codecs="vp8"'),
            webm_vp9: video.canPlayType('video/webm; codecs="vp9"'),
            webm_av1: video.canPlayType('video/webm; codecs="av01"'),
            ogg_theora: video.canPlayType('video/ogg; codecs="theora"'),
        };
        return { codecs };
    } catch (e) {
        return { codecs: null };
    }
}

async function getMediaDevicesInfo() {
    try {
        if (!navigator.mediaDevices || !navigator.mediaDevices.enumerateDevices) {
            return { audioInputs: 0, videoInputs: 0, audioOutputs: 0 };
        }
        const devices = await navigator.mediaDevices.enumerateDevices();
        return {
            audioInputs: devices.filter(d => d.kind === 'audioinput').length,
            videoInputs: devices.filter(d => d.kind === 'videoinput').length,
            audioOutputs: devices.filter(d => d.kind === 'audiooutput').length,
        };
    } catch (e) {
        return { audioInputs: 0, videoInputs: 0, audioOutputs: 0 };
    }
}

function getStorageInfo() {
    const info = {
        localStorage: false,
        sessionStorage: false,
        indexedDB: false,
        cookies: false,
    };

    try {
        info.localStorage = !!window.localStorage;
        window.localStorage.setItem('__fp_test', '1');
        window.localStorage.removeItem('__fp_test');
    } catch (e) {
        info.localStorage = false;
    }

    try {
        info.sessionStorage = !!window.sessionStorage;
        window.sessionStorage.setItem('__fp_test', '1');
        window.sessionStorage.removeItem('__fp_test');
    } catch (e) {
        info.sessionStorage = false;
    }

    try {
        info.indexedDB = !!window.indexedDB;
    } catch (e) {
        info.indexedDB = false;
    }

    try {
        info.cookies = navigator.cookieEnabled;
    } catch (e) {
        info.cookies = false;
    }

    return info;
}

async function getPermissionsInfo() {
    const permissions = {};
    const toCheck = ['camera', 'microphone', 'geolocation', 'notifications', 'push', 'persistent-storage'];

    if (!navigator.permissions || !navigator.permissions.query) {
        return permissions;
    }

    for (const name of toCheck) {
        try {
            const result = await navigator.permissions.query({ name });
            permissions[name] = result.state;
        } catch (e) {
            permissions[name] = 'error';
        }
    }

    return permissions;
}

function getMathFingerprint() {
    try {
        return {
            tan: Math.tan(-1e300).toString(),
            sin: Math.sin(0.5).toString().slice(0, 20),
            cos: Math.cos(0.5).toString().slice(0, 20),
            exp: Math.exp(1).toString().slice(0, 20),
            log: Math.log(2).toString().slice(0, 20),
            sqrt: Math.sqrt(2).toString().slice(0, 20),
        };
    } catch (e) {
        return null;
    }
}

function getErrorStackFormat() {
    try {
        throw new Error('fp');
    } catch (e) {
        const stack = e.stack || '';
        // Extract just the format pattern, not specific line numbers
        if (stack.includes('at ')) return 'v8'; // Chrome/Node
        if (stack.includes('@')) return 'spidermonkey'; // Firefox
        if (stack.includes('global code')) return 'jsc'; // Safari
        return 'unknown';
    }
}

function getDateFormat() {
    try {
        const d = new Date(0);
        return {
            string: d.toString(),
            locale: d.toLocaleString(),
            timezone: d.getTimezoneOffset(),
        };
    } catch (e) {
        return null;
    }
}

function getScreenInfo() {
    try {
        const s = window.screen;
        return {
            width: s.width,
            height: s.height,
            availWidth: s.availWidth,
            availHeight: s.availHeight,
            colorDepth: s.colorDepth,
            pixelDepth: s.pixelDepth,
            orientation: s.orientation?.type || null,
            orientationAngle: s.orientation?.angle || null,
        };
    } catch (e) {
        return null;
    }
}

function getWindowInfo() {
    try {
        return {
            innerWidth: window.innerWidth,
            innerHeight: window.innerHeight,
            outerWidth: window.outerWidth,
            outerHeight: window.outerHeight,
            devicePixelRatio: window.devicePixelRatio,
        };
    } catch (e) {
        return null;
    }
}

function getNavigatorInfo() {
    try {
        const n = navigator;
        return {
            userAgent: n.userAgent || null,
            platform: n.platform || null,
            language: n.language || null,
            languages: n.languages ? Array.from(n.languages) : null,
            hardwareConcurrency: n.hardwareConcurrency || null,
            deviceMemory: n.deviceMemory || null,
            maxTouchPoints: n.maxTouchPoints || 0,
            vendor: n.vendor || null,
            vendorSub: n.vendorSub || null,
            product: n.product || null,
            productSub: n.productSub || null,
            appName: n.appName || null,
            appVersion: n.appVersion || null,
            doNotTrack: n.doNotTrack || null,
            cookieEnabled: n.cookieEnabled,
            pdfViewerEnabled: n.pdfViewerEnabled ?? null,
            webdriver: n.webdriver || false,
            buildID: n.buildID || null, // Firefox-specific
        };
    } catch (e) {
        return null;
    }
}

function getConnectionInfo() {
    try {
        const conn = navigator.connection || navigator.mozConnection || navigator.webkitConnection;
        if (!conn) return null;
        return {
            effectiveType: conn.effectiveType || null,
            downlink: conn.downlink || null,
            rtt: conn.rtt || null,
            saveData: conn.saveData || false,
        };
    } catch (e) {
        return null;
    }
}

function getBatteryInfo() {
    // Just check if API is available, don't actually get battery status
    return {
        available: 'getBattery' in navigator,
    };
}

function getTouchInfo() {
    return {
        ontouchstart: 'ontouchstart' in window,
        maxTouchPoints: navigator.maxTouchPoints || 0,
        touchEvent: 'TouchEvent' in window,
    };
}

function getIntlInfo() {
    try {
        const dtf = new Intl.DateTimeFormat();
        const resolved = dtf.resolvedOptions();
        return {
            timezone: resolved.timeZone || null,
            locale: resolved.locale || null,
            calendar: resolved.calendar || null,
            numberingSystem: resolved.numberingSystem || null,
        };
    } catch (e) {
        return null;
    }
}

export async function collectDeviceFingerprint() {
    try {
        // Collect all data in parallel where possible
        const [
            mediaDevices,
            permissions,
        ] = await Promise.all([
            getMediaDevicesInfo(),
            getPermissionsInfo(),
        ]);

        const webglInfo = getWebGLInfo();
        const canvasData = getCanvasFingerprint();
        const pluginsInfo = getPluginsInfo();
        const mimeTypesInfo = getMimeTypesInfo();
        const audioInfo = getAudioInfo();
        const videoInfo = getVideoInfo();
        const storageInfo = getStorageInfo();
        const mathFingerprint = getMathFingerprint();
        const screenInfo = getScreenInfo();
        const windowInfo = getWindowInfo();
        const navigatorInfo = getNavigatorInfo();
        const connectionInfo = getConnectionInfo();
        const batteryInfo = getBatteryInfo();
        const touchInfo = getTouchInfo();
        const intlInfo = getIntlInfo();
        const errorStackFormat = getErrorStackFormat();
        const dateFormat = getDateFormat();

        // Compute hashes for complex data
        const canvasHash = canvasData ? await computeSha256Hash(canvasData) : null;
        const webglHash = (webglInfo.vendor && webglInfo.renderer)
            ? await computeSha256Hash(webglInfo.vendor + '|' + webglInfo.renderer)
            : null;
        const webglExtensionsHash = webglInfo.extensions
            ? await computeSha256Hash(webglInfo.extensions.sort().join(','))
            : null;
        const webglParamsHash = webglInfo.params
            ? await computeSha256Hash(JSON.stringify(webglInfo.params))
            : null;
        const pluginsHash = pluginsInfo.count > 0
            ? await computeSha256Hash(JSON.stringify(pluginsInfo.list))
            : null;
        const audioCodecsHash = audioInfo.codecs
            ? await computeSha256Hash(JSON.stringify(audioInfo.codecs))
            : null;
        const videoCodecsHash = videoInfo.codecs
            ? await computeSha256Hash(JSON.stringify(videoInfo.codecs))
            : null;
        const mathHash = mathFingerprint
            ? await computeSha256Hash(JSON.stringify(mathFingerprint))
            : null;

        // Build the full fingerprint object
        // Keep legacy fields at top level for backwards compatibility
        const fingerprint = {
            // Legacy fields (kept for backwards compat with existing indexed columns)
            screenWidth: screenInfo?.width || null,
            screenHeight: screenInfo?.height || null,
            colorDepth: screenInfo?.colorDepth || null,
            pixelRatio: windowInfo?.devicePixelRatio || null,
            timezone: intlInfo?.timezone || null,
            timezoneOffset: new Date().getTimezoneOffset(),
            language: navigatorInfo?.language || null,
            languages: navigatorInfo?.languages || null,
            platform: navigatorInfo?.platform || null,
            hardwareConcurrency: navigatorInfo?.hardwareConcurrency || null,
            deviceMemory: navigatorInfo?.deviceMemory || null,
            touchSupport: touchInfo.ontouchstart || touchInfo.maxTouchPoints > 0,
            canvasHash,
            webglVendor: webglInfo.vendor,
            webglRenderer: webglInfo.renderer,
            webglHash,

            // Extended attributes (stored in JSONB blob)
            attributes: {
                // Screen (extended)
                screen: screenInfo,
                window: windowInfo,

                // Navigator (extended)
                navigator: navigatorInfo,

                // Plugins & MIME types
                plugins: {
                    count: pluginsInfo.count,
                    hash: pluginsHash,
                },
                mimeTypes: {
                    count: mimeTypesInfo.count,
                },

                // WebGL (extended)
                webgl: {
                    vendor: webglInfo.vendor,
                    renderer: webglInfo.renderer,
                    extensionsCount: webglInfo.extensions?.length || 0,
                    extensionsHash: webglExtensionsHash,
                    paramsHash: webglParamsHash,
                },

                // Audio
                audio: {
                    sampleRate: audioInfo.sampleRate,
                    destination: audioInfo.destination,
                    codecsHash: audioCodecsHash,
                },

                // Video
                video: {
                    codecsHash: videoCodecsHash,
                },

                // Media devices
                mediaDevices,

                // Storage capabilities
                storage: storageInfo,

                // Permissions
                permissions,

                // Connection
                connection: connectionInfo,

                // Battery API availability
                battery: batteryInfo,

                // Touch capabilities
                touch: touchInfo,

                // Internationalization
                intl: intlInfo,

                // Math precision fingerprint
                mathHash,

                // Error stack format (browser detection)
                errorStackFormat,

                // Date format
                dateFormat: dateFormat ? {
                    timezoneOffset: dateFormat.timezone,
                } : null,

                // Timestamp of collection
                collectedAt: Date.now(),
            },
        };

        return fingerprint;
    } catch (e) {
        console.error('[DeviceFingerprint] Error collecting:', e);
        return null;
    }
}

export async function sendDeviceFingerprint(userAddress) {
    if (!userAddress) return;

    try {
        const fingerprint = await collectDeviceFingerprint();
        if (!fingerprint) return;

        await Api.post('core/fp', {
            user_address: userAddress,
            ...fingerprint,
        }, { timeoutMs: 5000 });
    } catch (e) {
        // Silently fail - fingerprinting is non-critical
    }
}

const Fingerprint = { collectDeviceFingerprint, sendDeviceFingerprint };
export default Fingerprint;
