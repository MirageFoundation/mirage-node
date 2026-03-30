/**
 * Old reddit uses `OldRedditShell` for the top bar and primary nav on all viewports.
 * A second mobile-only strip (brand + balance + search) would duplicate that chrome.
 *
 * Manifest registers `MobileHeader: NullComponent`; routes import this file directly,
 * so this module must stay a no-op.
 */
export default function MobileHeader() {
    return null;
}
