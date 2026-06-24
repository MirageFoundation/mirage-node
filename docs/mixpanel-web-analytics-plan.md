# Mixpanel Web Analytics Plan

## Goal

Add Mixpanel analytics to the Mirage web app with the same privacy and identity model used in the mobile app, while making web and mobile traffic easy to separate in Mixpanel reports.

This document is a plan only. It does not implement Mixpanel yet.

## Existing mobile implementation reviewed

Mobile already has a dedicated analytics wrapper at:

- `mirage-mobile-app/src/services/analytics.ts`

Key mobile patterns to mirror on web:

- Mixpanel is imported only inside one wrapper service.
- Analytics is consent-gated. Until a user opts in, tracking calls are no-ops.
- `distinct_id` is the wallet address via `identifyUser(walletAddress)`.
- Analytics state is reset on logout.
- Common helpers exist for:
  - `initAnalytics()`
  - `setAnalyticsTrackingEnabled(enabled)`
  - `identifyUser(walletAddress, profile)`
  - `updateUserProfile(profile)`
  - `registerTierSuperProperty(tier)`
  - `resetAnalyticsIdentity()`
  - `trackEvent(event, properties)`
  - `flushAnalytics()`
- Mobile tracks core events such as onboarding, signup/login, post creation, comments, votes, follows, and topic follows.

Mobile currently registers these super properties:

- `platform`: React Native platform (`ios` / `android`)
- `app_version`: Expo app version

## Web app areas to integrate

The web app lives under `web/frontend` and is a Create React App style React app.

Important files and hook points:

- `web/frontend/package.json`
  - Add the browser SDK dependency, likely `mixpanel-browser`.
- `web/frontend/src/App.js`
  - Initialize analytics when stored consent is granted.
  - Identify user when credentials are set or restored.
  - Reset identity on logout via `setCredentials('', '', '')`.
  - Optionally track page views from `RouteTracker`.
- `web/frontend/src/logic/useSettings.js`
  - Add persisted analytics consent state and a handler to toggle tracking.
- `web/frontend/src/themes/*/routes/SettingsView.js`
  - Add a Usage Analytics toggle in Settings for each active theme route that renders settings.
  - The default theme already has a natural section structure where a Privacy section can be added.
- `web/frontend/src/logic/useCreateAccount.js`
  - Track `onboarding_started`, `username_set`, and `sign_up_completed` where appropriate.
- `web/frontend/src/logic/useLogin.js`
  - Track `login_completed` after successful wallet import/login.
- `web/frontend/src/logic/useCreatePost.js`
  - Track `post_create_opened` and `post_created`.
- `web/frontend/src/logic/useViewPost.js`
  - Track comments, follows from post detail, and topic follows.
- `web/frontend/src/logic/useVote.js`
  - Track `vote_cast`.
- Follow/subscription utilities and hooks:
  - Track `user_followed` and `topic_followed` in the hook or utility layer that confirms success.

## Recommended web analytics service

Create a web-only wrapper:

- `web/frontend/src/utils/analytics.js`

Proposed public API:

```js
export function initAnalytics() {}
export function setAnalyticsTrackingEnabled(enabled) {}
export function isAnalyticsActive() {}
export function identifyUser(walletAddress, profile) {}
export function updateUserProfile(profile) {}
export function registerTierSuperProperty(tier) {}
export function resetAnalyticsIdentity() {}
export function trackEvent(event, properties) {}
export function flushAnalytics() {}
```

Implementation notes:

- Use `mixpanel-browser`.
- Read token from `process.env.REACT_APP_MIXPANEL_TOKEN`.
- Avoid hard-coding the token if possible; if the same public project token is intentionally reused, configure it in build/deploy env.
- Store consent in existing `Storage` using a key such as `analytics_consent`.
- Keep the wrapper no-op until consent is granted.
- Strip undefined/null/empty-string properties before tracking, matching mobile behavior.
- Enable Mixpanel debug logging only in development.
- Call `mixpanel.opt_in_tracking()` after consent is granted.
- Call `mixpanel.opt_out_tracking()` and `mixpanel.reset()` when consent is revoked.
- Call `mixpanel.reset()` on logout/account switch.

## Consent UX plan

Mirror mobile's consent-gated approach:

1. Default to analytics disabled.
2. Add a Settings toggle: `Usage Analytics`.
3. Copy suggestion:
   - Title: `Usage Analytics`
   - Description: `Share anonymous usage data to help improve Mirage.`
4. Optional first-run prompt can be added later, but the first implementation can rely on Settings to minimize UX changes.
5. If a first-run prompt is added, store both:
   - `analytics_consent`
   - `analytics_consent_asked`

## Identity model

Use the same distinct id on web and mobile:

- `distinct_id = wallet address`

This lets Mixpanel show one Mirage user across web and mobile when they use the same wallet.

On web:

- Identify after login/signup once `publicKey` exists.
- Identify on app startup if consent is enabled and `publicKey` is already stored.
- Set people/profile properties when known:
  - `username`
  - `tier`
- Reset identity when signing out or switching accounts.

Privacy note:

- Wallet address is pseudonymous but still user-linked. Keep consent required before calling `identify`.
- Do not track seed phrases, private keys, raw post content, DMs, or sensitive form values.

## Differentiating website vs mobile app

Yes, this is straightforward and should be done with super properties on every event.

Recommended shared super properties:

```js
{
  app_surface: 'web',          // web | mobile
  client_app: 'mirage_web',    // mirage_web | mirage_mobile
  platform: 'web',             // web | ios | android
  app_version: process.env.REACT_APP_VERSION || 'unknown'
}
```

Mobile should be updated to register equivalent properties:

```ts
{
  app_surface: 'mobile',
  client_app: 'mirage_mobile',
  platform: Platform.OS,
  app_version: Constants.expoConfig?.version ?? 'unknown'
}
```

Why both `app_surface` and `platform`?

- `app_surface` gives a simple top-level split: web vs mobile.
- `platform` gives detailed device split: web, ios, android.
- `client_app` is stable if future clients are added, such as admin, desktop, or extension.

In Mixpanel, dashboards can then filter or break down by:

- `app_surface`
- `client_app`
- `platform`

Recommended project setup:

- Use one Mixpanel project for both web and mobile if the goal is cross-platform user journeys and unified funnels.
- Use the properties above to split reports by source.
- Use separate projects only if compliance, access control, or completely separate dashboards are required.

## Event taxonomy

Start with the same mobile event names so dashboards work across both clients.

Initial event list:

- `analytics_consent_granted`
- `page_viewed` web-only event for route analytics
- `onboarding_started`
- `username_set`
- `recovery_phrase_viewed`
- `sign_up_completed`
- `login_completed`
- `post_create_opened`
- `post_created`
- `comment_posted`
- `vote_cast`
- `user_followed`
- `topic_followed`

Suggested common properties:

- All events automatically get super properties above.
- `page_viewed`
  - `path`
  - `route_family`, such as `home`, `topic`, `profile`, `post`, `settings`, `search`, `other`
- `sign_up_completed`
  - `sign_up_method`: `wallet_created`
- `login_completed`
  - `login_method`: `wallet_import` or another known method
- `post_created`
  - `topic`
  - `has_media`
  - `media_type` when available
- `comment_posted`
  - `post_id` only if acceptable; otherwise avoid IDs and track only `topic` / `reply_depth`
- `vote_cast`
  - `direction`: `up` / `down`
  - `target_type`: `post` / `comment`
- `user_followed`
  - Avoid raw followed address if unnecessary; use counts or boolean context if possible.
- `topic_followed`
  - `topic`

## Implementation sequence

1. Add dependency and env
   - Add `mixpanel-browser` to `web/frontend/package.json`.
   - Add `REACT_APP_MIXPANEL_TOKEN` to web build/deploy environment.

2. Add web analytics wrapper
   - Create `web/frontend/src/utils/analytics.js`.
   - Include consent-gated initialization, identity helpers, tracking helpers, and source super properties.

3. Wire app startup and identity
   - Import analytics helpers in `App.js`.
   - On app startup, if `analytics_consent` is true, initialize analytics and identify stored `publicKey`.
   - In `setCredentials`, identify when logging in/signing up and reset when logging out.

4. Add Settings consent toggle
   - Extend `useSettings` with `analyticsConsent` and `handleAnalyticsToggle`.
   - Add `Usage Analytics` toggle in Settings UI.
   - Apply the same UI change to each theme route that implements Settings, or refactor settings sections if desired.

5. Add page tracking
   - In `RouteTracker`, call `trackEvent('page_viewed', ...)` when pathname/search changes.
   - Keep route properties sanitized; do not send full sensitive query strings if any are added later.

6. Add core product events
   - Add event calls at successful action boundaries only, not button-click attempts.
   - Prioritize signup/login, post creation, comments, votes, follows, and topic follows.

7. Update mobile source properties
   - Add `app_surface: 'mobile'` and `client_app: 'mirage_mobile'` to mobile analytics super properties.
   - Keep `platform: Platform.OS` for iOS vs Android reporting.

8. Validate
   - Run `npm install` in `web/frontend` after adding the dependency.
   - Run `npm run build` from `web/frontend`.
   - Manually test opt-in, tracking, identify, logout reset, and opt-out.
   - Confirm Mixpanel events include `app_surface`, `client_app`, `platform`, and `app_version`.

## Open decisions before implementation

- Should web use the same Mixpanel project token as mobile or a separate web token?
  - Recommendation: same project, same token, with source properties.
- Do we want a first-run consent prompt on web, or only a Settings toggle for v1?
  - Recommendation: Settings toggle first; add prompt after copy/design approval.
- Are wallet addresses acceptable as Mixpanel distinct IDs for web under the current privacy policy?
  - Recommendation: yes if consent-gated, because mobile already uses the same model.
- Should post IDs / followed user addresses be sent as event properties?
  - Recommendation: avoid raw user addresses and content identifiers unless a dashboard requires them.

## Success criteria

- Web events appear in Mixpanel only after consent is granted.
- Users can disable analytics from Settings, which opts out and clears analytics state.
- Logged-in web users are identified by wallet address, matching mobile.
- Reports can clearly separate web and mobile by `app_surface`, `client_app`, or `platform`.
- No private keys, seed phrases, wallet contents, raw post body, or other sensitive data are sent.
