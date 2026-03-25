import React, { Component } from 'react';
import { BrowserRouter, Routes, Route, useLocation, useNavigate } from 'react-router-dom';
import { HelmetProvider } from 'react-helmet-async';
import { GlobalStyle } from './styled/GlobalStyle';
import { ThemeProvider } from 'styled-components';
import styled from 'styled-components';
import Storage from './utils/Storage';
import seedVault from './utils/SeedVault';
import Api from './lib/api';
import * as tx from './utils/tx';

import MobileBottomNav from './components/MobileBottomNav';
import UnlockPrompt from './components/UnlockPrompt';
import Toast from './components/Toast';


// Lazy import wrapper that handles chunk load failures after deployments.
// When a new version is deployed, old chunk files are replaced. Users with stale
// main.js will fail to load missing chunks. This wrapper detects chunk errors and
// triggers a page reload to fetch the new main.js with correct chunk references.
const CHUNK_RELOAD_KEY = 'chunk_reload_attempted';

function lazyWithRetry(importFn) {
    return React.lazy(() =>
        importFn().catch((error) => {
            // Check if this is a chunk load error (typically ChunkLoadError or similar)
            const isChunkError =
                error?.name === 'ChunkLoadError' ||
                error?.message?.includes('Loading chunk') ||
                error?.message?.includes('Failed to fetch dynamically imported module') ||
                error?.message?.includes("expected expression, got '<'");

            if (isChunkError) {
                // Prevent infinite reload loops: only reload once per session
                const hasReloaded = sessionStorage.getItem(CHUNK_RELOAD_KEY);
                if (!hasReloaded) {
                    console.warn('[Mirage] Chunk load error detected, reloading to fetch updated app...');
                    sessionStorage.setItem(CHUNK_RELOAD_KEY, 'true');
                    window.location.reload();
                    // Return a never-resolving promise to prevent React from rendering an error
                    return new Promise(() => { });
                } else {
                    console.error('[Mirage] Chunk load error persists after reload:', error);
                }
            }
            // Re-throw if not a chunk error or if reload already attempted
            throw error;
        })
    );
}

const MainView = lazyWithRetry(() => import('./views/MainView'));
const CreatePostView = lazyWithRetry(() => import('./views/CreatePostView'));
const CreateAccountView = lazyWithRetry(() => import('./views/CreateAccountView'));
const LoginView = lazyWithRetry(() => import('./views/LoginView'));
const ChangeUsernameView = lazyWithRetry(() => import('./views/ChangeUsernameView'));
const SignOutView = lazyWithRetry(() => import('./views/SignOutView'));
const ViewPostView = lazyWithRetry(() => import('./views/ViewPostView'));
const ProfileView = lazyWithRetry(() => import('./views/ProfileView'));
const NetworkView = lazyWithRetry(() => import('./views/NetworkView'));
const SubscriptionView = lazyWithRetry(() => import('./views/SubscriptionView'));
const ReportsView = lazyWithRetry(() => import('./views/ReportsView'));
const InboxView = lazyWithRetry(() => import('./views/InboxView'));
const SettingsView = lazyWithRetry(() => import('./views/SettingsView'));
const DiscoverView = lazyWithRetry(() => import('./views/DiscoverView'));
const StatsView = lazyWithRetry(() => import('./views/StatsView'));
const WelcomeView = lazyWithRetry(() => import('./views/WelcomeView'));
const SearchResultsView = lazyWithRetry(() => import('./views/SearchResultsView'));
const FollowsView = lazyWithRetry(() => import('./views/FollowsView'));
const BlocksView = lazyWithRetry(() => import('./views/BlocksView'));
const AgentsView = lazyWithRetry(() => import('./views/AgentsView'));
const BridgeView = lazyWithRetry(() => import('./views/BridgeView'));
const NotFoundView = lazyWithRetry(() => import('./views/NotFoundView'));
const APP_VERSION = process.env.REACT_APP_VERSION || '';
const APP_BUILD_ID = process.env.REACT_APP_BUILD_ID || '';
const darkTheme = {
    name: 'dark',
    colors: {
        bg: '#1A1A1A',
        text: '#FFFFFF',
        subtleText: '#CCCCCC',
        panel: '#23272C',
        panelAlt: '#33373C',
        border: '#444',
        accent: '#2E3238',
        accentHover: '#3A3F46',
        accentDisabled: '#4A4F55',
        buttonText: '#FFFFFF',
        link: '#FFFFFF',
        linkHover: '#CCCCCC',
        scrollbar: '#CCCCCC',
    }
};

const lightTheme = {
    name: 'light',
    colors: {
        bg: '#FFFFFF',
        text: '#111827',
        subtleText: '#4B5563',
        panel: '#F7F7F8',
        panelAlt: '#EFEFF1',
        border: '#D1D5DB',
        accent: '#E5E7EB',
        accentHover: '#D1D5DB',
        accentDisabled: '#F3F4F6',
        buttonText: '#111827',
        link: '#111827',
        linkHover: '#374151',
        scrollbar: '#9CA3AF',
    }
};

// Hoist styled component out of render to keep component identity stable across renders
const SiteContainer = styled.div`
            width: 100%;
            max-width: 100%;
            margin: 0 auto;
            padding: 0 1rem;
            padding-bottom: 3rem;
            @media (max-width: 1000px) {
                padding: 0 0.25rem;
                padding-bottom: 3rem;
            }
            @media (min-width: 1000px) {
                max-width: 80%;
            }
            /* Extra bottom padding on mobile for bottom nav */
            @media (max-width: 600px) {
                padding-bottom: 80px;
            }
        `;

// Routes that should not be saved/restored
const excludedRoutes = [
    '/login',
    '/signup',
    '/welcome',
    '/sign_out',
    '/p/',
    '/create_post'
];

// Routes that are safe to restore on startup (avoid restoring transient/deprecated routes)
const restorableRoutePrefixes = [
    '/home',
    '/following',
    '/t/',
    '/profile',
    '/u/',
    '/settings',
    '/follows',
    '/blocks',
    '/agents',
    '/subscription',
    '/network',
    '/server',
    '/reports',
    '/inbox',
    '/topics',
    '/stats',
    '/search',
    '/bridge',
];

// Component to track and restore the last route
function RouteTracker({ children }) {
    const location = useLocation();
    const navigate = useNavigate();
    const isInitialMountRef = React.useRef(true);
    const lastTrackedPathRef = React.useRef(null);

    // Track page views for stats (debounced, skip root redirect)
    React.useEffect(() => {
        // Record activity for inactivity auto-logout
        try { Storage.touchLastSeen(); } catch (_) { }

        // REFERRALS DISABLED FOR NOW
        // Capture referrer parameter from URL (for referral system)
        // try {
        //     const params = new URLSearchParams(location.search);
        //     const referrerAddr = params.get('referrer');
        //     console.log('[Referral] URL search:', location.search, 'referrer param:', referrerAddr);
        //     if (referrerAddr && referrerAddr.startsWith('mirage1') && referrerAddr.length >= 39) {
        //         localStorage.setItem('referrer_address', referrerAddr);
        //         console.log('[Referral] Saved referrer to localStorage:', referrerAddr);
        //     }
        // } catch (e) { console.error('[Referral] Error capturing referrer:', e); }

        // Skip tracking root path since it redirects to the last route
        if (location.pathname === '/') return;
        // Skip if we already tracked this path
        if (lastTrackedPathRef.current === location.pathname) return;

        const trackPageView = async () => {
            try {
                let sessionId = Storage.load('stats_session_id', null);
                const storedTime = Storage.load('stats_session_time', 0);
                const now = Date.now();
                const isNewSession = !sessionId || !storedTime || (now - storedTime) > 30 * 60 * 1000;

                if (isNewSession) {
                    sessionId = 'sess_' + now + '_' + Math.random().toString(36).substr(2, 9);
                    Storage.save('stats_session_id', sessionId);
                    Storage.save('stats_session_time', now);
                }

                const userAddress = Storage.load('publicKey', null);
                const pagePath = location.pathname;

                // Track visit and session_start only on first page load of new session
                if (isInitialMountRef.current && isNewSession) {
                    // Combine visit and session_start into a single "visit" event
                    await Api.post('stats/event', {
                        event_type: 'visit',
                        session_id: sessionId,
                        user_address: userAddress,
                        page_path: pagePath
                    }, { timeoutMs: 5000 });
                }

                // Track page_view only for subsequent navigations (not initial load)
                if (!isInitialMountRef.current) {
                    await Api.post('stats/event', {
                        event_type: 'page_view',
                        session_id: sessionId,
                        user_address: userAddress,
                        page_path: pagePath
                    }, { timeoutMs: 5000 });
                }

                Storage.save('stats_session_time', now);
                lastTrackedPathRef.current = location.pathname;
            } catch (_) {
                // Silently fail
            }
        };

        trackPageView();
    }, [location.pathname, location.search]);

    // Restore last route on mount if at root
    React.useEffect(() => {
        if (isInitialMountRef.current) {
            isInitialMountRef.current = false;
            if (location.pathname === '/') {
                try {
                    const lastRoute = Storage.load('last_route', null);
                    if (
                        lastRoute &&
                        typeof lastRoute === 'string' &&
                        lastRoute !== '/' &&
                        !excludedRoutes.some(route => lastRoute.startsWith(route)) &&
                        restorableRoutePrefixes.some(route => lastRoute.startsWith(route))
                    ) {
                        navigate(lastRoute, { replace: true });
                    } else {
                        navigate('/home', { replace: true });
                    }
                } catch (_) {
                    navigate('/home', { replace: true });
                }
            } else {
                // If we're not at root, ensure the current route is saved (in case it wasn't saved before)
                const path = location.pathname;
                if (path && path !== '/' && !excludedRoutes.some(route => path.startsWith(route))) {
                    try {
                        Storage.save('last_route', path);
                    } catch (_) {
                        // Ignore storage errors
                    }
                }
            }
        }
    }, [navigate, location.pathname]);

    // Save current route whenever it changes (excluding certain routes)
    React.useEffect(() => {
        const path = location.pathname;
        if (path && path !== '/' && !excludedRoutes.some(route => path.startsWith(route))) {
            try {
                Storage.save('last_route', path);
            } catch (_) {
                // Ignore storage errors
            }
        }
    }, [location.pathname]);

    // Track the last feed route for deterministic in-app "Back" behavior.
    // This is used when a post is opened directly (no history) and we need a reasonable
    // place to send the user back to.
    React.useEffect(() => {
        const pathname = location.pathname;
        const search = location.search || '';
        const path = pathname === '/' ? '/home' : pathname;
        const full = `${path}${search}`;

        const isFeedRoute =
            path === '/home' ||
            path === '/following' ||
            path.startsWith('/t/');

        if (!isFeedRoute) return;

        try { Storage.save('last_feed_route', full); } catch (_) { }
    }, [location.pathname, location.search]);

    return children;
}

class App extends Component {
    constructor() {
        super();

        // Load postUpdate from local storage or cookies (initialize as an empty object if not found)
        this.state = {
            publicKey: Storage.load('publicKey', ''),
            username: Storage.load('username', ''),
            seedPhrase: seedVault.getSeed() || '',
            vaultLocked: false,
            posts: [],
            deletedPosts: new Set(), // Track locally deleted post IDs to filter them out
            shouldWarnOnLeave: false,
            topic: "all",
        };

        this.setPosts = this.setPosts.bind(this);
        this.updatePost = this.updatePost.bind(this);
        this.getPost = this.getPost.bind(this);
        this.setTopic = this.setTopic.bind(this);
        this.applyVotesToExistingPosts = this.applyVotesToExistingPosts.bind(this);

        this.setCredentials = this.setCredentials.bind(this);
        this.setWarnOnLeave = this.setWarnOnLeave.bind(this);
        this.state.themeMode = Storage.load('theme_mode', 'time');
        this.state.theme = this.calculateTheme(this.state.themeMode);
    }

    // Session end tracking via sendBeacon on page unload
    setupSessionEndTracking() {
        window.addEventListener('beforeunload', () => {
            try {
                const sessionId = Storage.load('stats_session_id', null);
                if (!sessionId) return;

                const userAddress = this.state.publicKey || null;
                const pagePath = window.location.pathname;

                const data = JSON.stringify({
                    event_type: 'session_end',
                    session_id: sessionId,
                    user_address: userAddress,
                    page_path: pagePath
                });

                navigator.sendBeacon('/api/stats/event', data);
            } catch (_) {
                // Ignore errors
            }
        });
    }

    // Approximate light/dark switch times based on day of year (no location needed)
    // Uses a mid-latitude approximation that varies seasonally
    // Returns times for when to switch themes, not actual sunrise/sunset
    getApproximateSunTimes(date) {
        const dayOfYear = Math.floor((date - new Date(date.getFullYear(), 0, 0)) / 86400000);

        // Seasonal variation using sinusoidal approximation
        // Day 172 (Jun 21) = summer solstice, longest days
        // Day 355 (Dec 21) = winter solstice, shortest days
        const seasonalAngle = 2 * Math.PI * (dayOfYear - 172) / 365;
        const seasonalFactor = Math.cos(seasonalAngle);

        // Base times (equinox): sunrise 6:30 AM (390 min), sunset 6:30 PM (1110 min)
        // Summer variation: sunrise earlier by up to 1h, sunset later by up to 1.5h
        // Winter variation: sunrise later by up to 1h, sunset earlier by up to 1.5h
        const sunriseMinutes = 390 - seasonalFactor * 60;
        const astronomicalSunset = 1110 + seasonalFactor * 90;

        // Add twilight buffer: keep light theme 30 min after sunset (civil twilight)
        // This feels more natural since it's not truly dark right at sunset
        const sunsetMinutes = astronomicalSunset + 30;

        return { sunrise: sunriseMinutes, sunset: sunsetMinutes };
    }

    // Get current time in minutes from midnight
    getCurrentTimeMinutes() {
        const now = new Date();
        return now.getHours() * 60 + now.getMinutes();
    }

    // Calculate theme based on mode
    calculateTheme(mode) {
        if (mode === 'dark') return 'dark';
        if (mode === 'light') return 'light';
        if (mode === 'system') {
            try {
                return (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) ? 'dark' : 'light';
            } catch (_) {
                return 'dark';
            }
        }
        if (mode === 'time') {
            try {
                const now = new Date();
                const { sunrise, sunset } = this.getApproximateSunTimes(now);
                const currentMinutes = this.getCurrentTimeMinutes();

                if (currentMinutes > sunrise && currentMinutes < sunset) {
                    return 'light';
                }
                return 'dark';
            } catch (_) {
                return 'dark';
            }
        }
        // Default fallback
        return 'dark';
    }

    componentDidMount() {
        // Clear chunk reload flag on successful mount - this allows future deploys to trigger
        // a fresh reload if needed. We clear it here because if we got to componentDidMount,
        // the app has loaded successfully.
        try { sessionStorage.removeItem(CHUNK_RELOAD_KEY); } catch (_) { }

        // On hard refresh (or any full page reload), invalidate cached config timestamps
        // so views re-fetch chain/node config from the backend.
        try {
            const navEntries = performance.getEntriesByType('navigation');
            const isReload = navEntries.length > 0
                ? navEntries[0].type === 'reload'
                : performance.navigation?.type === 1;
            if (isReload) {
                Storage.remove('chain_config_cached_at');
                Storage.remove('node_config_cached_at');
            }
        } catch (_) { }

        // Security: if user hasn't used the site in 30 days, force logout and clear ALL local storage.
        // (We also clear sessionStorage to avoid restoring stale feed caches.)
        try {
            const lastSeen = Storage.getLastSeenMs();
            const now = Date.now();
            const THIRTY_DAYS_MS = 30 * 24 * 60 * 60 * 1000;
            if (lastSeen && (now - lastSeen) > THIRTY_DAYS_MS) {
                console.warn('[Security] Inactive for > 30 days. Clearing local storage and logging out.');
                Storage.hardResetAllStorage();
                window.location.replace('/');
                return;
            }
            // Touch on startup too (for first visit / fresh sessions)
            Storage.touchLastSeen();
        } catch (_) { /* noop */ }

        // Check if SeedVault needs unlock (password or passkey mode).
        // Skip on /login — the user either navigated there directly or chose
        // "sign in with recovery phrase instead". The login page shows a link
        // back to the unlock screen if an encrypted seed exists.
        if (seedVault.isLocked() && window.location.pathname !== '/login') {
            // Stash publicKey/username out of the main localStorage keys so that
            // nothing in the app (MainView, Sidebar, API calls, etc.) can access
            // them until the vault is unlocked. This prevents a duplicated tab
            // from leaking a logged-in session behind the unlock overlay.
            const pk = Storage.load('publicKey', '');
            const un = Storage.load('username', '');
            if (pk && !Storage.load('vault_owner', null)) {
                Storage.save('vault_owner', { publicKey: pk, username: un });
            }
            Storage.remove('publicKey');
            Storage.remove('username');
            this.setState({ vaultLocked: true, publicKey: '', username: '', seedPhrase: '' });
        }

        // Memory-only mode: user has credentials but no seed (tab was closed).
        // Redirect to login so they can re-enter their recovery phrase.
        if (seedVault.getMode() === 'memory' && !seedVault.getSeed() && this.state.publicKey) {
            Storage.remove('publicKey');
            Storage.remove('username');
            this.setState({ publicKey: '', username: '', seedPhrase: '' });
            window.location.replace('/login');
            return;
        }

        const version = APP_VERSION || 'dev';
        const buildId = APP_BUILD_ID || '';
        console.log('[Mirage] Frontend version:', version + (buildId ? ' (' + buildId + ')' : ''));
        try { window.__MIRAGE_BUILD__ = { version: version, buildId: buildId || null }; } catch (_) { }

        // Initialize full width mode CSS custom properties
        try {
            const fullWidthMode = Storage.load('full_width_mode', false) === true;
            const root = document.documentElement;
            if (fullWidthMode) {
                root.style.setProperty('--content-max-width', 'none');
                root.style.setProperty('--feed-max-width', 'none');
            } else {
                root.style.setProperty('--content-max-width', '1240px');
                root.style.setProperty('--feed-max-width', '1000px');
            }
        } catch (_) { }

        // Stats tracking is handled by RouteTracker to avoid duplicate requests
        // Only set up session end tracking via sendBeacon
        this.setupSessionEndTracking();

        // Keybind: Ctrl+. to toggle theme
        this._onKeyDown = (e) => {
            if ((e.ctrlKey || e.metaKey) && (e.key === '.' || e.code === 'Period')) {
                e.preventDefault();
                this.toggleTheme();
            }
        };
        window.addEventListener('keydown', this._onKeyDown);

        // Listen for theme mode changes from SettingsView
        this._onThemeModeChange = (e) => {
            const newMode = e.detail?.mode || 'time';
            // Clear existing interval if any
            if (this._timeThemeInterval) {
                clearInterval(this._timeThemeInterval);
                this._timeThemeInterval = null;
            }
            // Set up new interval if switching to time mode
            if (newMode === 'time') {
                this._timeThemeInterval = setInterval(() => {
                    this.updateTheme();
                }, 60000);
            }
            this.setState({ themeMode: newMode }, () => {
                this.updateTheme();
            });
        };
        window.addEventListener('themeModeChanged', this._onThemeModeChange);

        // Follow system theme (only if mode is 'system')
        try {
            this._themeMql = window.matchMedia('(prefers-color-scheme: dark)');
            this._onSystemThemeChange = (e) => {
                if (this.state.themeMode === 'system') {
                    try { document.documentElement.classList.add('theme-switching'); } catch (_) { }
                    this.setState({ theme: e.matches ? 'dark' : 'light' }, () => {
                        setTimeout(() => { try { document.documentElement.classList.remove('theme-switching'); } catch (_) { } }, 0);
                    });
                }
            };
            if (this._themeMql && this._themeMql.addEventListener) {
                this._themeMql.addEventListener('change', this._onSystemThemeChange);
            } else if (this._themeMql && this._themeMql.addListener) {
                this._themeMql.addListener(this._onSystemThemeChange);
            }
        } catch (_) { }

        // Update time-based theme periodically (every minute)
        if (this.state.themeMode === 'time') {
            this._timeThemeInterval = setInterval(() => {
                this.updateTheme();
            }, 60000); // Check every minute
        }
        // existing setup
        // Wire callbacks lazily through facade
        try { tx.setWarnOnLeaveCallback(this.setWarnOnLeave); } catch (_) { }
        try { tx.updatePostCallback(this.updatePost); } catch (_) { }
        try { tx.getPostCallback(this.getPost); } catch (_) { }

        // Fetch node config if missing, not cached, or stale (> 1h)
        // Chain config is fetched lazily by views that need it (CreatePostView, ViewPostView, SubscriptionView).
        try {
            const nowMs = Date.now();
            const nodeCachedAt = Number(Storage.load('node_config_cached_at', '0') || 0);
            const nodeConfigCached = Storage.load('nodeConfig', null);
            const hasNodeConfig = !!(nodeConfigCached && typeof nodeConfigCached === 'object');
            const nodeStale = !nodeCachedAt || (nowMs - nodeCachedAt) > 3600_000 || !hasNodeConfig;
            if (nodeStale) {
                Api.get('get_node_config', undefined)
                    .then((cfg) => { if (cfg) try { tx.cacheNodeConfig(cfg); } catch (_) { } })
                    .catch(() => { })
                    .finally(() => {
                        // Always notify listeners a config fetch attempt completed.
                        // Without this, create-account can stay on "Loading..." forever
                        // if the request fails before nodeConfig is cached.
                        try { window.dispatchEvent(new Event('nodeConfigUpdated')); } catch (_) { }
                    });
            }
        } catch (_) { }

        // Refresh user balance on every page load for logged-in users
        try {
            const pk = this.state.publicKey || Storage.load('publicKey', '');
            if (pk) {
                Api.get('get_user_status', { address: pk, _cb: Date.now() })
                    .then((data) => { if (data) try { tx.cacheUserStatus(data); } catch (_) { } })
                    .catch(() => { });
            }
        } catch (_) { }

        // Add the "beforeunload" event listener
        window.addEventListener('beforeunload', this.handleBeforeUnload);

        // Listen for LoginView requesting to show the vault unlock screen.
        // Don't restore publicKey/username to state here — that would trigger
        // LoginView's redirect to /profile. They get restored after successful unlock.
        this._onShowVaultUnlock = () => {
            if (seedVault.isLocked()) {
                this.setState({ vaultLocked: true });
            }
        };
        window.addEventListener('showVaultUnlock', this._onShowVaultUnlock);
    }

    componentWillUnmount() {
        try { window.removeEventListener('keydown', this._onKeyDown); } catch (_) { }
        try { window.removeEventListener('beforeunload', this.handleBeforeUnload); } catch (_) { }
        try { window.removeEventListener('showVaultUnlock', this._onShowVaultUnlock); } catch (_) { }
        try { window.removeEventListener('themeModeChanged', this._onThemeModeChange); } catch (_) { }
        try {
            if (this._themeMql && this._themeMql.removeEventListener) {
                this._themeMql.removeEventListener('change', this._onSystemThemeChange);
            } else if (this._themeMql && this._themeMql.removeListener) {
                this._themeMql.removeListener(this._onSystemThemeChange);
            }
        } catch (_) { }
        try {
            if (this._timeThemeInterval) {
                clearInterval(this._timeThemeInterval);
            }
        } catch (_) { }
    }

    updateTheme() {
        const newTheme = this.calculateTheme(this.state.themeMode);
        if (newTheme !== this.state.theme) {
            try { document.documentElement.classList.add('theme-switching'); } catch (_) { }
            this.setState({ theme: newTheme }, () => {
                setTimeout(() => { try { document.documentElement.classList.remove('theme-switching'); } catch (_) { } }, 0);
            });
        }
    }

    setCredentials(publicKey, username, seedPhrase) {
        this.setState({
            publicKey: publicKey,
            username: username,
            seedPhrase: seedPhrase,
        });

        Storage.save('publicKey', publicKey);
        Storage.save('username', username);
        // Store seed through SeedVault (respects chosen security mode).
        // If the current mode requires a secret we don't have (e.g. user re-entered
        // seed via fallback login while mode is 'password'), fall back to insecure.
        if (seedPhrase) {
            seedVault.storeSeed(seedPhrase, seedVault.getMode(), null).catch((e) => {
                console.warn('[SeedVault] Falling back to insecure mode:', e.message);
                return seedVault.storeSeed(seedPhrase, 'insecure', null);
            }).catch((e) => {
                console.error('[SeedVault] Failed to store seed:', e);
            });
        } else {
            seedVault.clear();
        }

        // Clear old cached data (from previous wallet)
        Storage.remove('chainConfig');
        Storage.remove('nodeConfig');
        Storage.remove('chain_config_cached_at');
        Storage.remove('node_config_cached_at');
        Storage.remove('user_balance');
        Storage.remove('profile_followed_cache');
        Storage.remove('profile_no_cache_until');

        // Fetch latest status on login
        try {
            if (publicKey) {
                // Node config already fetched by componentDidMount; no need to re-fetch on login.
                // Chain config fetched lazily by views that need it.

                // Fetch user-specific data (cache-bust to ensure fresh balance)
                Api.get('get_user_status', { address: publicKey, _cb: Date.now() })
                    .then((userStatus) => {
                        if (!userStatus) {
                            console.warn('[App] No user status returned from API');
                            return;
                        }

                        // Cache user data
                        try { tx.cacheUserStatus(userStatus); } catch (_) { }

                        // Update username in state if returned from backend
                        if (typeof userStatus.username === 'string' && userStatus.username) {
                            this.setState({ username: userStatus.username });
                        }

                        // Prime recent votes for local highlight (only on login)
                        try {
                            if (Array.isArray(userStatus.recent_votes)) {
                                const votes = {};
                                for (const v of userStatus.recent_votes) {
                                    if (!v || !v.target) continue;
                                    votes[String(v.target).toLowerCase()] = Number(v.direction || 0);
                                }
                                // Keep only a small cache; API provides user_vote for fetched items.
                                // This is just to preserve quick highlight across reloads before indexing catches up.
                                try {
                                    const keys = Object.keys(votes);
                                    const pruned = {};
                                    const keep = keys.slice(-100);
                                    for (const k of keep) pruned[k] = votes[k];
                                    Storage.save('votes', pruned);
                                } catch (_) {
                                    Storage.save('votes', votes);
                                }
                                // Update existing posts in state with vote directions
                                this.applyVotesToExistingPosts();
                            }
                        } catch (_) { }
                    })
                    .catch((err) => {
                        console.error('[App] User status fetch failed:', err);
                    });
            }
        } catch (e) {
            console.error('[App] setCredentials error:', e);
        }
    }

    updatePost = (postId, values) => {

        // Update the post in state
        this.setState((prevState) => {
            const existing = (prevState.posts && prevState.posts[postId]) ? prevState.posts[postId] : {};
            const updated = { ...existing, ...values };

            // If deleted flag is set, remove the post from state entirely and track it
            if (updated.deleted) {
                const updatedPosts = { ...prevState.posts };
                delete updatedPosts[postId];
                const deletedPosts = new Set(prevState.deletedPosts || []);
                deletedPosts.add(String(postId).toLowerCase());
                return { posts: updatedPosts, deletedPosts };
            }

            // If blocked flag is set, remove the post from state entirely (client-side hide)
            if (updated.blocked) {
                const updatedPosts = { ...prevState.posts };
                delete updatedPosts[postId];
                return { posts: updatedPosts };
            }

            return {
                posts: {
                    ...prevState.posts,
                    [postId]: updated,
                }
            };
        });

        // Do not persist direction here; handled by config bootstrap and transient writes on cast
    };

    getPost = (postId) => {
        return this.state.posts[postId];
    };

    applyVotesToExistingPosts = () => {
        this.setState((prevState) => {
            const savedVotes = Storage.load('votes', {});
            if (!savedVotes || Object.keys(savedVotes).length === 0) {
                return null;
            }

            const updatedPosts = { ...prevState.posts };
            let hasChanges = false;

            for (const postId in updatedPosts) {
                if (!updatedPosts.hasOwnProperty(postId)) continue;
                const key = String(postId).toLowerCase();
                const dir = savedVotes[key];
                if (dir !== undefined && dir !== null && updatedPosts[postId].direction !== dir) {
                    updatedPosts[postId] = {
                        ...updatedPosts[postId],
                        direction: dir
                    };
                    hasChanges = true;
                }
            }

            return hasChanges ? { posts: updatedPosts } : null;
        });
    };

    setPosts = (newPosts, lastFetched) => {

        this.setState((prevState) => {
            // Merge the new posts into the existing posts dictionary
            const updatedPosts = { ...prevState.posts };
            const deletedPosts = prevState.deletedPosts || new Set();

            // Load localStorage votes once (authoritative source for user's own votes)
            const localVotes = Storage.load('votes', {}) || {};

            // Iterate over each new post
            for (let postId in newPosts) {
                if (!newPosts.hasOwnProperty(postId)) continue;
                const key = String(postId).toLowerCase();

                // Skip posts that were locally deleted
                if (deletedPosts.has(key)) {
                    continue;
                }

                // Direction priority: localStorage > server user_vote > existing state > incoming direction
                // localStorage is authoritative because it reflects the user's most recent action
                let dir;
                const localDir = localVotes[key];
                if (typeof localDir === 'number') {
                    dir = localDir;
                } else {
                    const incomingUserVote = newPosts[postId]?.user_vote ?? newPosts[postId]?.my_vote ?? newPosts[postId]?.userVote ?? newPosts[postId]?.myVote;
                    if (incomingUserVote !== undefined && incomingUserVote !== null && Number.isFinite(Number(incomingUserVote))) {
                        dir = Number(incomingUserVote);
                    } else {
                        const existingDir = prevState.posts[postId]?.direction;
                        const incomingDir = newPosts[postId]?.direction;
                        if (typeof existingDir === 'number') dir = existingDir;
                        else if (typeof incomingDir === 'number') dir = incomingDir;
                        else dir = null;
                    }
                }

                if (prevState.posts[postId]) {
                    const existing = prevState.posts[postId];
                    updatedPosts[postId] = {
                        ...existing,
                        ...newPosts[postId],
                        direction: dir
                    };
                } else {
                    updatedPosts[postId] = {
                        ...newPosts[postId],
                        direction: dir
                    };
                }
            }

            return {
                posts: updatedPosts,
                lastFetched,
            };
        });
    };


    setWarnOnLeave(flag) {
        this.setState({ shouldWarnOnLeave: flag });
    }

    setTopic(topic) {
        this.setState({ topic: topic });
    }

    // Handler for the "beforeunload" event
    handleBeforeUnload = (event) => {
        if (this.state.shouldWarnOnLeave) {
            event.preventDefault();
            event.returnValue = ''; // This triggers the browser's default confirmation dialog
        }
    };

    handleVaultUnlocked = () => {
        const seed = seedVault.getSeed() || '';
        // Restore credentials — either from vault_owner stash (after fallback login)
        // or directly from localStorage (normal unlock on fresh tab).
        const owner = Storage.load('vault_owner', null);
        const pk = owner?.publicKey || Storage.load('publicKey', '');
        const un = owner?.username || Storage.load('username', '');
        if (owner) {
            Storage.save('publicKey', pk);
            Storage.save('username', un);
            Storage.remove('vault_owner');
        }
        this.setState({ vaultLocked: false, seedPhrase: seed, publicKey: pk, username: un }, () => {
            // Always go home after unlocking
            window.history.replaceState(null, '', '/');
            window.dispatchEvent(new PopStateEvent('popstate'));
        });
    };

    handleFallbackLogin = () => {
        // Lock the vault (clear in-memory secrets) but keep the encrypted blobs
        // in localStorage so the login page can offer a link back to the unlock screen.
        // Stash publicKey/username under a separate key so they can be restored after
        // unlock, but remove them from the main keys so the app doesn't leak a
        // logged-in state (MainView etc. read publicKey directly from localStorage).
        const pk = Storage.load('publicKey', '');
        const un = Storage.load('username', '');
        if (pk) Storage.save('vault_owner', { publicKey: pk, username: un });
        Storage.remove('publicKey');
        Storage.remove('username');

        seedVault.lock();
        this.setState({ vaultLocked: false, seedPhrase: '', publicKey: '', username: '' }, () => {
            // Client-side navigate to /login (no full reload, no flicker)
            window.history.replaceState(null, '', '/login');
            window.dispatchEvent(new PopStateEvent('popstate'));
        });
    };

    toggleTheme = () => {
        // Toggle between dark and light, but preserve themeMode
        this.setState((prev) => {
            const newTheme = prev.theme === 'dark' ? 'light' : 'dark';
            // Temporarily override themeMode for toggle
            const tempMode = newTheme === 'dark' ? 'dark' : 'light';
            Storage.save('theme_mode', tempMode);
            return { theme: newTheme, themeMode: tempMode };
        });
    };

    render() {
        const themeObj = this.state.theme === 'light' ? lightTheme : darkTheme;
        return (
            <HelmetProvider>
                <ThemeProvider theme={themeObj}>
                    <div>
                        <GlobalStyle state={this.state} />
                        <Toast />

                        {this.state.vaultLocked && (
                            <UnlockPrompt
                                mode={seedVault.getMode()}
                                onUnlocked={this.handleVaultUnlocked}
                                onFallbackLogin={this.handleFallbackLogin}
                            />
                        )}

                        <BrowserRouter>
                            <RouteTracker>
                                <SiteContainer>
                                    <React.Suspense fallback={null}>
                                        <Routes>
                                            {/* MobileBottomNav renders in its own Suspense below */}
                                            <Route
                                                path="/"
                                                element={<MainView state={this.state} setPosts={this.setPosts} updatePost={this.updatePost} setTopic={this.setTopic} routeTopic="home" />}
                                            />
                                            <Route
                                                path="/home"
                                                element={<MainView state={this.state} setPosts={this.setPosts} updatePost={this.updatePost} setTopic={this.setTopic} routeTopic="home" />}
                                            />
                                            <Route
                                                path="/following"
                                                element={<MainView state={this.state} setPosts={this.setPosts} updatePost={this.updatePost} setTopic={this.setTopic} routeTopic="following" />}
                                            />
                                            <Route
                                                path="/t/:topic"
                                                element={<MainView state={this.state} setPosts={this.setPosts} updatePost={this.updatePost} setTopic={this.setTopic} />}
                                            />

                                            <Route path="/create_post" element={<CreatePostView state={this.state} setPosts={this.setPosts} updatePost={this.updatePost} />} />
                                            <Route path="/signup" element={<CreateAccountView state={this.state} setCredentials={this.setCredentials} />} />
                                            <Route path="/login" element={<LoginView state={this.state} setCredentials={this.setCredentials} />} />
                                            <Route path="/welcome" element={<WelcomeView state={this.state} />} />
                                            <Route path="/change_username" element={<ChangeUsernameView state={this.state} />} />
                                            <Route path="/sign_out" element={<SignOutView state={this.state} setCredentials={this.setCredentials} />} />
                                            {/* New clean URL routes */}
                                            <Route path="/p/:postId" element={<ViewPostView state={this.state} updatePost={this.updatePost} />} />
                                            <Route path="/u/:identity" element={<ProfileView state={this.state} />} />
                                            <Route path="/profile" element={<ProfileView state={this.state} />} />

                                            <Route path="/follows" element={<FollowsView state={this.state} />} />
                                            <Route path="/blocks" element={<BlocksView state={this.state} />} />
                                            <Route path="/agents" element={<AgentsView state={this.state} />} />
                                            <Route path="/settings" element={<SettingsView state={this.state} />} />
                                            <Route path="/subscription" element={<SubscriptionView state={this.state} />} />
                                            <Route path="/network" element={<NetworkView state={this.state} />} />
                                            <Route path="/server" element={<NetworkView state={this.state} />} />
                                            <Route path="/reports" element={<ReportsView state={this.state} />} />
                                            <Route path="/inbox" element={<InboxView state={this.state} />} />
                                            <Route path="/topics" element={<DiscoverView state={this.state} />} />
                                            <Route path="/stats" element={<StatsView />} />
                                            <Route path="/search" element={<SearchResultsView state={this.state} />} />
                                            <Route path="/bridge" element={<BridgeView state={this.state} />} />
                                            <Route path="*" element={<NotFoundView state={this.state} />} />
                                        </Routes>
                                    </React.Suspense>
                                </SiteContainer>
                                <MobileBottomNav state={this.state} />
                            </RouteTracker>
                        </BrowserRouter>
                    </div>
                </ThemeProvider>
            </HelmetProvider>
        );
    }
}

export default App;
