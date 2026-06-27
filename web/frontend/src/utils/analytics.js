import mixpanel from 'mixpanel-browser';
import Storage from './Storage';

const MIXPANEL_TOKEN = process.env.REACT_APP_MIXPANEL_TOKEN || '';
const IS_DEV = process.env.NODE_ENV !== 'production';
const CONSENT_KEY = 'analytics_consent';
const TRACKING_OPTIONS = { persistence_type: 'localStorage' };

const EVENT_NAMES = new Set([
    'analytics_consent_granted',
    'page_viewed',
    'onboarding_started',
    'username_set',
    'recovery_phrase_viewed',
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

export async function initAnalytics() {
    if (!trackingEnabled) return;
    if (!MIXPANEL_TOKEN) {
        if (IS_DEV) console.warn('[Analytics] Missing REACT_APP_MIXPANEL_TOKEN');
        return;
    }
    if (initialized) return;
    if (initializing) return initializing;

    initializing = Promise.resolve().then(() => {
        mixpanel.init(MIXPANEL_TOKEN, {
            ...TRACKING_OPTIONS,
            debug: IS_DEV
        });
        mixpanel.register(getSuperProperties());
        initialized = true;
        if (IS_DEV) console.log('[Analytics] Mixpanel initialized');
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

export function identifyUser(walletAddress, profile = {}) {
    if (!isAnalyticsActive() || !walletAddress) return;
    mixpanel.identify(walletAddress);
    const profileProps = stripUndefined({
        username: profile.username,
        tier: profile.tier,
        app_surface: 'web',
        client_app: 'mirage_web',
        platform: 'web'
    });
    if (Object.keys(profileProps).length > 0) {
        mixpanel.people.set(profileProps);
    }
}

export function updateUserProfile(profile = {}) {
    if (!isAnalyticsActive()) return;
    const props = stripUndefined({
        username: profile.username,
        tier: profile.tier
    });
    if (Object.keys(props).length > 0) {
        mixpanel.people.set(props);
    }
}

export function registerTierSuperProperty(tier) {
    if (!isAnalyticsActive() || !tier) return;
    mixpanel.register({ tier });
}

export function resetAnalyticsIdentity() {
    if (!initialized) return;
    mixpanel.reset();
    if (trackingEnabled) {
        mixpanel.register(getSuperProperties());
    }
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
