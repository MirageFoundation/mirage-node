import React, { Component } from 'react';
import { BrowserRouter, Routes, Route, useLocation, useNavigate, Navigate, useParams } from 'react-router-dom';
import { HelmetProvider } from 'react-helmet-async';
import { ThemeProvider } from 'styled-components';
import Storage from './utils/Storage';
import seedVault from './utils/SeedVault';
import Api from './utils/api';
import { captureFirstTouchAttribution } from './utils/visitorId';
import AuthPromptModal from './components/AuthPromptModal';
import * as tx from './utils/tx';
import { seedFromBootstrap as seedProfileFromBootstrap } from './utils/ProfileCache';
import { deriveBootstrapView } from './utils/bootstrapView';
import { getAllowedTagsParam } from './utils/ContentTags';
import { getResolvedTheme, getThemeFamily, normalizeThemeId, DEFAULT_THEME_ID } from './registry/theme';

import UnlockPrompt from './components/UnlockPrompt';
import Toast from './components/Toast';
import { installCrossTabSessionWatcher, onSessionReset, resetClientSession } from './utils/sessionLifecycle';
import { updateNotification } from './utils/notifications';


// Lazy import wrapper that handles chunk load failures after deployments.
// When a new version is deployed, old chunk files are replaced. Users with stale
// main.js will fail to load missing chunks. This wrapper detects chunk errors and
// triggers a page reload to fetch the new main.js with correct chunk references.
const CHUNK_RELOAD_KEY = 'chunk_reload_attempted';

function chunkReloadAttempted() {
    try {
        return sessionStorage.getItem(CHUNK_RELOAD_KEY) !== null;
    } catch (_) { /* noop */ }
    return false;
}

function setChunkReloadAttempted(attempted) {
    try {
        if (attempted) sessionStorage.setItem(CHUNK_RELOAD_KEY, 'true');
        else sessionStorage.removeItem(CHUNK_RELOAD_KEY);
    } catch (_) { /* noop */ }
}

function lazyWithRetry(importFn) {
    return React.lazy(() =>
        importFn().then((loaded) => {
            // Re-arm the guard. Without this a tab gets one rescue for its whole
            // life, so a second deploy while it is still open strands it again.
            setChunkReloadAttempted(false);
            return loaded;
        }).catch((error) => {
            // Any failure is treated as a stale bundle. These are same-origin
            // imports of files the running build shipped with, so they resolve
            // unless a deploy renamed them. This used to match the failure text
            // against a list that only held Chrome's wording: Firefox says
            // "error loading dynamically imported module" and Safari says
            // "Importing a module script failed", so on those browsers the
            // reload never fired and the route stayed blank until the user
            // refreshed by hand. Tracking each browser's prose is not
            // maintainable, so it no longer tries.
            if (navigator.onLine === false) {
                // Reloading with no network replaces the app with the browser's
                // offline page, which is worse than reporting the failure.
                throw error;
            }
            if (chunkReloadAttempted()) {
                console.error('[Mirage] Chunk load error persists after reload:', error);
                throw error;
            }
            console.warn('[Mirage] Chunk load error detected, reloading to fetch updated app...', error);
            setChunkReloadAttempted(true);
            window.location.reload();
            // Never resolve, so React does not render an error mid-reload.
            return new Promise(() => { });
        })
    );
}

const MainView = lazyWithRetry(() => import('./views/MainView'));
const CreatePostView = lazyWithRetry(() => import('./views/CreatePostView'));
const CreateAccountView = lazyWithRetry(() => import('./views/CreateAccountView'));
const LoginView = lazyWithRetry(() => import('./views/LoginView'));
const ChangeUsernameView = lazyWithRetry(() => import('./views/ChangeUsernameView'));
const CurationTeamsView = lazyWithRetry(() => import('./themes/default/routes/CurationTeamsView'));
const CurationTeamView = lazyWithRetry(() => import('./themes/default/routes/CurationTeamView'));
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
const FAQView = lazyWithRetry(() => import('./views/FAQView'));
const NotFoundView = lazyWithRetry(() => import('./views/NotFoundView'));
const APP_VERSION = typeof __MIRAGE_APP_VERSION__ === 'string' ? __MIRAGE_APP_VERSION__ : '';

// Routes that should not be saved/restored
const excludedRoutes = [
    '/login',
    '/signup',
    '/welcome',
    '/sign_out',
    '/p/',
    '/create_post',
    '/communities/new',
];

// Routes that are safe to restore on startup (avoid restoring transient/deprecated routes)
const restorableRoutePrefixes = [
    '/home',
    '/following',
    '/c/',
    '/t/',
    '/profile',
    '/u/',
    '/settings',
    '/follows',
    '/blocks',
    '/faq',
    '/subscription',
    '/network',
    '/server',
    '/reports',
    '/inbox',
    '/communities',
    '/topics',
    '/stats',
    '/search',
];

function TopicToCommunityRedirect() {
    const { topic } = useParams();
    return <Navigate to={`/c/${topic || ''}`} replace />;
}

// Component to track and restore the last route
function RouteTracker({ children }) {
    const location = useLocation();
    const navigate = useNavigate();
    const isInitialMountRef = React.useRef(true);

    React.useEffect(() => {
        const navEntry = performance.getEntriesByType('navigation')[0];
        if (navEntry && navEntry.type === 'reload') {
            window.scrollTo(0, 0);
        }
    }, []);

    React.useEffect(() => {
        try { Storage.touchLastSeen(); } catch (_) { }
    }, [location.pathname]);

    React.useEffect(() => {
        captureFirstTouchAttribution();
    }, [location.search]);

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
        {
            const raw = Storage.load('theme_id', DEFAULT_THEME_ID);
            const themeId = normalizeThemeId(raw);
            if (themeId !== raw) Storage.save('theme_id', themeId);
            this.state.themeId = themeId;
        }
        this.state.themeMode = Storage.load('theme_mode', 'system');
        this.state.theme = this.calculateTheme(this.state.themeMode);
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

        // On hard refresh, invalidate the chain_config timestamp only — chain config
        // is genuinely volatile (params, difficulty). nodeConfig is deployment-static
        // and matches the backend's 24h cache; we keep it across reloads. It's still
        // cleared in setCredentials() on login/logout in case the active validator differs.
        try {
            const navEntries = performance.getEntriesByType('navigation');
            const isReload = navEntries.length > 0
                ? navEntries[0].type === 'reload'
                : performance.navigation?.type === 1;
            if (isReload) {
                Storage.remove('chain_config_cached_at');
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
        console.log('[Mirage] Frontend version:', version);
        try { window.__MIRAGE_BUILD__ = { version: version }; } catch (_) { }

        // Keybind: Ctrl+. to toggle theme
        this._onKeyDown = (e) => {
            if ((e.ctrlKey || e.metaKey) && (e.key === '.' || e.code === 'Period')) {
                e.preventDefault();
                this.toggleTheme();
            }
        };
        window.addEventListener('keydown', this._onKeyDown);

        // Protected-vault auto-lock + activity refresh
        this._onVaultActivity = () => {
            try { seedVault.touchActivity(); } catch (_) { /* noop */ }
        };
        ['pointerdown', 'keydown', 'touchstart'].forEach((evt) => {
            window.addEventListener(evt, this._onVaultActivity, { passive: true });
        });
        this._vaultAutoLockInterval = setInterval(() => {
            try {
                if (seedVault.checkAutoLock()) {
                    console.debug('[App] vault auto-locked');
                    // Keep public identity for unlock UI; seed is cleared in memory.
                    this.setState({ seedPhrase: '' });
                }
            } catch (_) { /* noop */ }
        }, 30_000);

        // Cross-tab session reset. Locking the vault alone leaves this tab's queue,
        // pending maps and PoW worker running, and leaves its session generation
        // unbumped, so a queued intent that predates the sign-out still matches if
        // the user signs back into the same account here.
        this._removeCrossTabWatcher = installCrossTabSessionWatcher(() => {
            resetClientSession({ reason: 'cross_tab_sign_out', clearVault: true, lockVault: true })
                .catch((e) => { console.error('[App] cross-tab session reset failed:', e?.message || e); });
            this.setState({ publicKey: '', username: '', seedPhrase: '' });
        });

        // Rendered posts carry the viewer's own user_vote, so they are account-bound
        // and must not outlive the session that fetched them.
        this._removeSessionResetSub = onSessionReset(({ reason }) => {
            try { console.debug('[App] clearing post state on session reset', { reason }); } catch (_) { /* noop */ }
            this.setState({ posts: [], deletedPosts: new Set(), topic: 'all' });
        });

        // A failed vault write leaves a session that renders as signed in but cannot
        // sign anything, so it has to be visible rather than a console line.
        this._onSeedVaultStoreFailed = (e) => {
            const msg = String(e?.detail?.message || 'Failed to store recovery phrase');
            updateNotification(`Could not save your recovery phrase: ${msg}`, 15, true);
        };
        window.addEventListener('seedVaultStoreFailed', this._onSeedVaultStoreFailed);

        // Listen for theme id changes from SettingsView
        this._onThemeIdChange = (e) => {
            const newId = normalizeThemeId(e.detail?.themeId || DEFAULT_THEME_ID);
            try { document.documentElement.setAttribute('data-theme-id', newId); } catch (_) { }
            this.setState({ themeId: newId });
        };
        window.addEventListener('themeIdChanged', this._onThemeIdChange);

        // Listen for theme mode changes from SettingsView
        this._onThemeModeChange = (e) => {
            const newMode = e.detail?.mode || 'system';
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

        // Single combined bootstrap fetch: replaces the cold-load fan-out of
        // get_node_config + get_chain_config + get_user_status + get_user_followed +
        // get_user_blocked + /rewards/summary + the initial
        // screen payload (feed/thread/inbox). Per-section nulls fall through
        // to the existing per-endpoint fetches; chain_config falls back to
        // _bootstrapChainConfig when missing from the response.
        try { this._bootstrapApp(); } catch (_) { }

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
        try {
            if (this._onVaultActivity) {
                ['pointerdown', 'keydown', 'touchstart'].forEach((evt) => {
                    window.removeEventListener(evt, this._onVaultActivity);
                });
            }
        } catch (_) { }
        try {
            if (this._vaultAutoLockInterval) clearInterval(this._vaultAutoLockInterval);
        } catch (_) { }
        try {
            if (typeof this._removeCrossTabWatcher === 'function') this._removeCrossTabWatcher();
        } catch (_) { }
        try {
            if (typeof this._removeSessionResetSub === 'function') this._removeSessionResetSub();
        } catch (_) { }
        try { window.removeEventListener('beforeunload', this.handleBeforeUnload); } catch (_) { }
        try { window.removeEventListener('showVaultUnlock', this._onShowVaultUnlock); } catch (_) { }
        try { window.removeEventListener('seedVaultStoreFailed', this._onSeedVaultStoreFailed); } catch (_) { }
        try { window.removeEventListener('themeIdChanged', this._onThemeIdChange); } catch (_) { }
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
        try {
            if (this._chainConfigRetryTimer) {
                clearTimeout(this._chainConfigRetryTimer);
                this._chainConfigRetryTimer = null;
            }
        } catch (_) { }
        try {
            if (this._nodeConfigRetryTimer) {
                clearTimeout(this._nodeConfigRetryTimer);
                this._nodeConfigRetryTimer = null;
            }
        } catch (_) { }
        try {
            if (this._bootstrapAppRetryTimer) {
                clearTimeout(this._bootstrapAppRetryTimer);
                this._bootstrapAppRetryTimer = null;
            }
        } catch (_) { }
    }

    _bootstrapChainConfig(attempt = 0) {
        const delays = [0, 1000, 3000];
        if (attempt >= delays.length) return;
        if (!tx.needsChainConfigRefresh()) return;

        const run = () => {
            if (!tx.needsChainConfigRefresh()) return;
            console.debug('[App] get_chain_config.fetch attempt', attempt + 1);
            Api.get('get_chain_config', undefined)
                .then((cfg) => {
                    if (cfg) {
                        try { tx.cacheChainConfig(cfg); } catch (_) { }
                    } else {
                        // Release the fetch claim so the retry (and any
                        // consumer hooks) can re-enter `needsChainConfigRefresh`.
                        try { tx.releaseChainConfigClaim(); } catch (_) { }
                        this._bootstrapChainConfig(attempt + 1);
                    }
                })
                .catch(() => {
                    try { tx.releaseChainConfigClaim(); } catch (_) { }
                    this._bootstrapChainConfig(attempt + 1);
                });
        };

        if (attempt === 0) {
            run();
        } else {
            this._chainConfigRetryTimer = setTimeout(run, delays[attempt]);
        }
    }

    _bootstrapNodeConfig(attempt = 0) {
        // Mirrors `_bootstrapChainConfig`: retry get_node_config on transient
        // failures so home cards (invite codes banner, quest hero), the profile
        // menu's Referrals item, and CreateAccountView don't render in their
        // "missing" state until the user manually refreshes.
        const delays = [0, 1000, 3000, 7000];
        if (attempt >= delays.length) {
            // Out of retries — wake up listeners (e.g. CreateAccountView) so
            // they can stop showing a permanent "Loading..." state.
            try { window.dispatchEvent(new Event('nodeConfigUpdated')); } catch (_) { }
            return;
        }

        const run = () => {
            console.debug('[App] get_node_config.fetch attempt', attempt + 1);
            Api.get('get_node_config', undefined)
                .then((cfg) => {
                    if (cfg && typeof cfg === 'object') {
                        // cacheNodeConfig stores + dispatches nodeConfigUpdated.
                        try { tx.cacheNodeConfig(cfg); } catch (_) { }
                    } else {
                        this._bootstrapNodeConfig(attempt + 1);
                    }
                })
                .catch(() => {
                    this._bootstrapNodeConfig(attempt + 1);
                });
        };

        if (attempt === 0) {
            run();
        } else {
            this._nodeConfigRetryTimer = setTimeout(run, delays[attempt]);
        }
    }

    _resolveBootstrapPathname() {
        // Mirror RouteTracker restoration: `/` may rewrite to last_route or /home
        // AFTER componentDidMount, so bootstrap must target the post-restore path.
        try {
            let path = (typeof window !== 'undefined' && window.location && window.location.pathname) || '/';
            path = String(path).split('?')[0] || '/';
            if (path === '/') {
                const lastRoute = Storage.load('last_route', null);
                if (
                    lastRoute &&
                    typeof lastRoute === 'string' &&
                    lastRoute !== '/' &&
                    !excludedRoutes.some(route => lastRoute.startsWith(route)) &&
                    restorableRoutePrefixes.some(route => lastRoute.startsWith(route))
                ) {
                    path = String(lastRoute).split('?')[0] || '/home';
                } else {
                    path = '/home';
                }
            }
            return path;
        } catch (_) {
            return '/home';
        }
    }

    _bootstrapApp(attempt = 0) {
        // Combined first-paint fetch via /api/bootstrap. Distributes results into
        // the existing caches so consumer hooks see the data on their first effect.
        // For logged-out users only node_config/chain_config (+ optional view) come
        // back; user_* sections are null. On failure, the per-endpoint hooks
        // (useMain blocked-topics fetcher, useQuests fetchAll, etc.) keep their
        // existing fetch logic and pick up the slack.
        const delays = [0, 1000, 3000, 7000];
        if (attempt >= delays.length) {
            // Out of retries: fire the same nodeConfigUpdated event the
            // standalone _bootstrapNodeConfig path would, so listeners stop
            // showing "Loading..." indefinitely.
            try { window.dispatchEvent(new Event('nodeConfigUpdated')); } catch (_) { }
            return;
        }

        const run = () => {
            const pk = this.state.publicKey || Storage.load('publicKey', '');
            const bootstrapPath = this._resolveBootstrapPathname();
            const view = deriveBootstrapView(bootstrapPath);

            // If we already have a fresh nodeConfig in localStorage AND there's no
            // logged-in user AND no initial view to embed, there's nothing for
            // bootstrap to do — skip the request entirely. (24h staleness matches
            // the backend's server-side cache.)
            const nowMs = Date.now();
            const nodeCachedAt = Number(Storage.load('node_config_cached_at', '0') || 0);
            const nodeConfigCached = Storage.load('nodeConfig', null);
            const hasFreshNodeConfig = !!(nodeConfigCached && typeof nodeConfigCached === 'object')
                && nodeCachedAt && (nowMs - nodeCachedAt) <= 86_400_000;
            if (!pk && hasFreshNodeConfig && !view) {
                console.debug('[App] bootstrap.skipped (anonymous + fresh node_config + no view)');
                // Reload clears chain_config_cached_at; still refresh chain config.
                try { this._bootstrapChainConfig(); } catch (_) { }
                return;
            }

            const params = {};
            if (pk) params.address = pk;
            if (view) {
                params.view = view;
                let by = Storage.load('home_sort_mode', 'magic');
                if (by !== 'magic' && by !== 'newest') by = 'magic';
                params.by = by;
                params.allowed_tags = getAllowedTagsParam();
                params.limit = 15;
            }

            console.debug('[App] bootstrap.fetch attempt', attempt + 1, 'logged_in:', !!pk, 'view:', view || null, 'path:', bootstrapPath);
            const requestPk = pk || '';
            const request = Api.get('bootstrap', Object.keys(params).length ? params : undefined)
                .then((resp) => {
                    if (!resp || typeof resp !== 'object') {
                        this._bootstrapApp(attempt + 1);
                        return;
                    }

                    if (resp.node_config && typeof resp.node_config === 'object') {
                        try { tx.cacheNodeConfig(resp.node_config); } catch (_) { }
                    } else if (!hasFreshNodeConfig) {
                        // node_config came back null: fall through to the legacy
                        // retrying fetcher so home cards eventually populate.
                        try { this._bootstrapNodeConfig(); } catch (_) { }
                    }

                    if (resp.chain_config) {
                        try { tx.cacheChainConfig(resp.chain_config); } catch (_) { }
                    } else {
                        // chain_config missing from bootstrap: fall back to the
                        // standalone get_chain_config path.
                        try { this._bootstrapChainConfig(); } catch (_) { }
                    }

                    const stashAt = Date.now();
                    if (resp.view) {
                        try {
                            Storage.save('bootstrap_view', { data: resp.view, at: stashAt, pk: requestPk });
                            console.debug('[Bootstrap] stashed view', {
                                kind: resp.view.kind,
                                feed: resp.view.feed,
                                topic: resp.view.topic,
                            });
                        } catch (_) { }
                    }

                    if (pk) {
                        if (resp.user_status) {
                            if (!Object.prototype.hasOwnProperty.call(resp, 'daily_quota') || !Object.prototype.hasOwnProperty.call(resp, 'renewal_warning')) {
                                throw new Error('bootstrap missing quota or renewal status');
                            }
                            try {
                                tx.cacheUserStatus({
                                    ...resp.user_status,
                                    daily_quota: resp.daily_quota,
                                    renewal_warning: resp.renewal_warning,
                                });
                            } catch (_) { }
                            // Surface backend-resolved username if missing from local state.
                            try {
                                const u = resp.user_status.username;
                                if (typeof u === 'string' && u && u !== this.state.username) {
                                    this.setState({ username: u });
                                }
                            } catch (_) { }
                            // Prime local recent votes for highlight continuity.
                            try {
                                const rv = resp.user_status.recent_votes;
                                if (Array.isArray(rv) && rv.length > 0) {
                                    const votes = {};
                                    for (const v of rv) {
                                        if (!v || !v.target) continue;
                                        votes[String(v.target).toLowerCase()] = Number(v.direction || 0);
                                    }
                                    try {
                                        const keys = Object.keys(votes);
                                        const pruned = {};
                                        const keep = keys.slice(-100);
                                        for (const k of keep) pruned[k] = votes[k];
                                        Storage.save('votes', pruned);
                                    } catch (_) {
                                        Storage.save('votes', votes);
                                    }
                                    this.applyVotesToExistingPosts();
                                }
                            } catch (_) { }
                        }
                        if (resp.user_followed) {
                            try { seedProfileFromBootstrap(pk, resp.user_followed); } catch (_) { }
                        }
                        if (resp.user_blocked) {
                            try { Storage.save('bootstrap_user_blocked', { data: resp.user_blocked, at: stashAt, pk }); } catch (_) { }
                        }
                        if (resp.rewards_summary) {
                            try { Storage.save('bootstrap_rewards_summary', { data: resp.rewards_summary, at: stashAt, pk }); } catch (_) { }
                        }
                    }

                    try { window.dispatchEvent(new Event('bootstrapHydrated')); } catch (_) { }
                })
                .catch(() => {
                    this._bootstrapApp(attempt + 1);
                })
                .finally(() => {
                    try {
                        if (window.__MIRAGE_BOOTSTRAP_PROMISE__ === request) {
                            window.__MIRAGE_BOOTSTRAP_PROMISE__ = null;
                            window.__MIRAGE_BOOTSTRAP_PK__ = '';
                        }
                    } catch (_) { }
                });
            try {
                window.__MIRAGE_BOOTSTRAP_PROMISE__ = request;
                window.__MIRAGE_BOOTSTRAP_PK__ = requestPk;
            } catch (_) { }
        };

        if (attempt === 0) {
            run();
        } else {
            this._bootstrapAppRetryTimer = setTimeout(run, delays[attempt]);
        }
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
        // Any owner stashed for the unlock screen is obsolete once credentials are set.
        Storage.remove('vault_owner');
        // Store seed through SeedVault. Never silently downgrade to insecure on error —
        // preserve the previous vault and surface the failure.
        if (seedPhrase) {
            seedVault.storeSeedForSession(seedPhrase).then(({ mode, requested }) => {
                if (mode !== requested) {
                    console.warn('[SeedVault] vault was locked; stored seed in memory mode', { requested });
                    updateNotification(
                        'Signed in for this session only — set up vault protection again in Settings.',
                        10,
                        true,
                    );
                }
            }).catch((e) => {
                console.error('[SeedVault] Failed to store seed (vault unchanged):', e?.message || e);
                try {
                    window.dispatchEvent(new CustomEvent('seedVaultStoreFailed', {
                        detail: { message: String(e?.message || e || 'Failed to store recovery phrase') },
                    }));
                } catch (_) { /* noop */ }
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
        Storage.remove('bootstrap_user_blocked');
        Storage.remove('bootstrap_rewards_summary');
        Storage.remove('bootstrap_view');

        // Fetch latest status on login via bootstrap (includes chain_config +
        // user sections). chain_config falls back inside _bootstrapApp when null.
        try {
            if (publicKey) {
                try { this._bootstrapApp(); } catch (_) { }
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
                if (!Object.prototype.hasOwnProperty.call(updatedPosts, postId)) continue;
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
                if (!Object.prototype.hasOwnProperty.call(newPosts, postId)) continue;
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
        try { document.documentElement.classList.add('theme-switching'); } catch (_) { }
        this.setState((prev) => {
            const newTheme = prev.theme === 'dark' ? 'light' : 'dark';
            const tempMode = newTheme === 'dark' ? 'dark' : 'light';
            Storage.save('theme_mode', tempMode);
            return { theme: newTheme, themeMode: tempMode };
        }, () => {
            setTimeout(() => { try { document.documentElement.classList.remove('theme-switching'); } catch (_) { } }, 0);
        });
    };

    render() {
        const themeObj = getResolvedTheme({ themeId: this.state.themeId, themeMode: this.state.theme });
        const family = getThemeFamily(this.state.themeId);
        const Shell = family.Shell;
        const Style = family.Style;
        return (
            <HelmetProvider>
                <ThemeProvider theme={themeObj}>
                    <div>
                        <Style />
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
                                <Shell state={this.state}>
                                    <AuthPromptModal />
                                    <React.Suspense fallback={null}>
                                        <Routes>
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
                                                path="/c/:topic/teams/new"
                                                element={<CurationTeamsView createOnly />}
                                            />
                                            <Route
                                                path="/c/:topic/teams/:teamId"
                                                element={<CurationTeamView />}
                                            />
                                            <Route
                                                path="/c/:topic/teams"
                                                element={<CurationTeamsView />}
                                            />
                                            <Route
                                                path="/c/:topic"
                                                element={<MainView state={this.state} setPosts={this.setPosts} updatePost={this.updatePost} setTopic={this.setTopic} />}
                                            />
                                            <Route path="/t/:topic" element={<TopicToCommunityRedirect />} />

                                            <Route path="/create_post" element={<CreatePostView state={this.state} setPosts={this.setPosts} updatePost={this.updatePost} />} />
                                            <Route path="/signup" element={<CreateAccountView state={this.state} setCredentials={this.setCredentials} />} />
                                            <Route path="/login" element={<LoginView state={this.state} setCredentials={this.setCredentials} />} />
                                            <Route path="/welcome" element={<WelcomeView state={this.state} />} />
                                            <Route path="/change_username" element={<ChangeUsernameView state={this.state} />} />
                                            <Route path="/sign_out" element={<SignOutView state={this.state} setCredentials={this.setCredentials} />} />
                                            <Route path="/p/:postId" element={<ViewPostView state={this.state} updatePost={this.updatePost} />} />
                                            <Route path="/u/:identity" element={<ProfileView state={this.state} />} />
                                            <Route path="/profile" element={<ProfileView state={this.state} />} />

                                            <Route path="/follows" element={<FollowsView state={this.state} />} />
                                            <Route path="/blocks" element={<BlocksView state={this.state} />} />
                                            <Route path="/agents" element={<Navigate to="/home" replace />} />
                                            <Route path="/faq" element={<FAQView state={this.state} />} />
                                            <Route path="/settings" element={<SettingsView state={this.state} />} />
                                            <Route path="/subscription" element={<SubscriptionView state={this.state} />} />
                                            <Route path="/network" element={<NetworkView state={this.state} />} />
                                            <Route path="/server" element={<NetworkView state={this.state} />} />
                                            <Route path="/reports" element={<ReportsView state={this.state} />} />
                                            <Route path="/inbox" element={<InboxView state={this.state} />} />
                                            <Route path="/curator-teams/new" element={<CurationTeamsView createOnly />} />
                                            <Route path="/communities" element={<DiscoverView state={this.state} />} />
                                            <Route path="/topics" element={<Navigate to="/communities" replace />} />
                                            <Route path="/stats" element={<StatsView />} />
                                            <Route path="/search" element={<SearchResultsView state={this.state} />} />
                                            <Route path="*" element={<NotFoundView state={this.state} />} />
                                        </Routes>
                                    </React.Suspense>
                                </Shell>
                            </RouteTracker>
                        </BrowserRouter>
                    </div>
                </ThemeProvider>
            </HelmetProvider>
        );
    }
}

export default App;
