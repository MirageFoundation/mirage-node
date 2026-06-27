import mixpanel from 'mixpanel-browser';
import Storage from './Storage';

// Build-time fallback (empty in the Docker bundle — only set by the CRA dev server).
const BUILD_TIME_MIXPANEL_TOKEN = (process.env.REACT_APP_MIXPANEL_TOKEN || '').trim();
const IS_DEV = process.env.NODE_ENV !== 'production';
const CONSENT_KEY = 'analytics_consent';

// Token comes from the backend node config at runtime (like the GIPHY key), because
// REACT_APP_* vars are NOT baked into the production bundle. Build-time env is a fallback.
function getMixpanelToken() {
    try {
        const raw = localStorage.getItem('nodeConfig');
        if (raw) {
            const config = JSON.parse(raw);
            if (config.mixpanel_token) return String(config.mixpanel_token).trim();
        }
    } catch (_) { }
    return BUILD_TIME_MIXPANEL_TOKEN;
}

// Anonymous, marketing-attribution-only analytics.
// We never identify users: no wallet address, no username, no mixpanel.identify.
// Mixpanel keeps its own random distinct_id so we can measure acquisition,
// funnel conversion and retention without tying anything to an on-chain identity.
// `ip: false` disables IP-based geolocation so we never build a wallet<->geo map.
const INIT_OPTIONS = {
    persistence_type: 'localStorage',
    ip: false
};

// First-touch marketing attribution params worth persisting to the conversion event.
const UTM_KEYS = ['utm_source', 'utm_medium', 'utm_campaign', 'utm_term', 'utm_content'];

const EVENT_NAMES = new Set([
    'analytics_consent_granted',
    'page_viewed',
    'onboarding_started',
    'username_set',
    'sign_up_completed',
    'login_completed',
    'post_create_opened',
    'post_created',
    'comment_posted',
    'vote_cast',
    'user_followed',
    'topic_followed'
]);

let initialized = false;
let initializing = null;
let trackingEnabled = Storage.load(CONSENT_KEY, false) === true;

function stripUndefined(props) {
    if (!props) return {};
    const result = {};
    Object.entries(props).forEach(([key, value]) => {
        if (value !== undefined && value !== null && value !== '') {
            result[key] = value;
        }
    });
    return result;
}

function getSuperProperties() {
    return {
        app_surface: 'web',
        client_app: 'mirage_web',
        platform: 'web',
        app_version: process.env.REACT_APP_VERSION || 'unknown'
    };
}

// Register first-touch UTM params so they stick to the eventual sign_up event.
// register_once never overwrites an existing value, preserving the original source.
function captureAttribution() {
    try {
        const params = new URLSearchParams(window.location.search || '');
        const attribution = {};
        UTM_KEYS.forEach((key) => {
            const value = params.get(key);
            if (value) attribution[key] = value;
        });
        if (Object.keys(attribution).length > 0) {
            mixpanel.register_once(attribution);
        }
    } catch (_) { }
}

export async function initAnalytics() {
    if (!trackingEnabled) return;
    const token = getMixpanelToken();
    if (!token) {
        // nodeConfig may not be cached yet on first load; init is retried on
        // the nodeConfigUpdated event once the backend config arrives.
        if (IS_DEV) console.warn('[Analytics] No Mixpanel token available yet');
        return;
    }
    if (initialized) return;
    if (initializing) return initializing;

    initializing = Promise.resolve().then(() => {
        mixpanel.init(token, {
            ...INIT_OPTIONS,
            debug: IS_DEV
        });
        mixpanel.register(getSuperProperties());
        captureAttribution();
        initialized = true;
        if (IS_DEV) console.log('[Analytics] Mixpanel initialized (anonymous)');
    }).catch((error) => {
        console.warn('[Analytics] Failed to initialize Mixpanel:', error);
    }).finally(() => {
        initializing = null;
    });

    return initializing;
}

export async function setAnalyticsTrackingEnabled(enabled) {
    trackingEnabled = !!enabled;
    Storage.save(CONSENT_KEY, trackingEnabled);

    if (trackingEnabled) {
        await initAnalytics();
        if (!initialized) return;
        mixpanel.opt_in_tracking();
        mixpanel.register(getSuperProperties());
        captureAttribution();
        mixpanel.track('analytics_consent_granted');
        mixpanel.flush();
        return;
    }

    if (initialized) {
        mixpanel.opt_out_tracking();
        mixpanel.reset();
        initialized = false;
    }
}

export function isAnalyticsActive() {
    return initialized && trackingEnabled;
}

export function trackEvent(event, properties = {}) {
    if (!EVENT_NAMES.has(event)) {
        if (IS_DEV) console.warn('[Analytics] Unknown event:', event);
    }
    if (!isAnalyticsActive()) {
        if (IS_DEV) console.log(`[Analytics] (no-op, no consent) ${event}`);
        return;
    }
    if (IS_DEV) console.log(`[Analytics] track: ${event}`, properties);
    mixpanel.track(event, stripUndefined(properties));
    if (IS_DEV) mixpanel.flush();
}

export function flushAnalytics() {
    if (initialized) mixpanel.flush();
}

export function hasAnalyticsConsent() {
    return trackingEnabled;
}
