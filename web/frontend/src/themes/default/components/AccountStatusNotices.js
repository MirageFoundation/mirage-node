import { useEffect, useState } from 'react';
import styled, { css } from 'styled-components';
import { Link } from 'react-router-dom';
import { HiOutlineBolt, HiOutlineClock } from 'react-icons/hi2';
import Storage from '../../../utils/Storage';
import { requireThemeColor } from '../../../utils/themeColor';

/**
 * Account status hero cards — `default` theme.
 *
 * Follows `docs/guides/web-theme-default/RULES.md`: cards sit on `bg` with a
 * 1px border and 8px radius (R1/R3), the renewal card uses the canonical amber
 * warning pair (R2 `warning*`), and type stays on the compact scale (R7 —
 * 0.78rem/600 title, 0.68rem/600 tally, 0.65rem body, 0.65rem/600 action pill).
 * Card geometry mirrors the app-download and NSFW consent heroes in
 * `routes/MainView.js`; the action pill follows SubscriptionView's StatusBadge.
 *
 * Both cards share one row order — header (icon, title, headline value) then
 * body then affordance — so the quota and renewal notices read as a set rather
 * than two unrelated blocks.
 */

// The horizontal inset tracks the gutter every host container uses, so the cards
// line up with the heading above them: HomeFeedTitleBar (`0.5rem 1rem`) on the
// feed, SectionBody (`0 1rem`, `0.85rem` at 1000px, flush at 600px) on
// Subscription / Settings / Profile. Going flush here outdents the cards past
// every sibling section.
const NoticeList = styled.div`
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
    margin: 0.35rem 1rem;

    @media (max-width: 1000px) {
        margin: 0.35rem 0.85rem;
    }

    @media (max-width: 600px) {
        margin: 0.35rem 0;
    }
`;

const NoticeCard = styled.div`
    box-sizing: border-box;
    width: 100%;
    max-width: 100%;
    align-self: flex-start;
    border-radius: 8px;
    padding: 0.7rem 1rem 0.75rem;
    display: flex;
    flex-direction: column;
    gap: 0.5rem;

    ${({ $tone, theme }) => {
        if ($tone === 'warning') {
            return css`
                background: ${requireThemeColor(theme, 'warningBg')};
                border: 1px solid ${requireThemeColor(theme, 'warningBorder')};
            `;
        }
        if ($tone === 'danger') {
            return css`
                background: ${requireThemeColor(theme, 'buttonDangerBg')};
                border: 1px solid ${requireThemeColor(theme, 'buttonDangerBorder')};
            `;
        }
        return css`
            background: ${requireThemeColor(theme, 'bg')};
            border: 1px solid ${requireThemeColor(theme, 'border')};
        `;
    }}

    @media (max-width: 600px) {
        border-radius: 6px;
        padding: 0.6rem 0.85rem 0.65rem;
    }
`;

const NoticeHeader = styled.div`
    display: flex;
    align-items: center;
    gap: 0.5rem;
    min-width: 0;
`;

const NoticeIconTile = styled.span`
    flex-shrink: 0;
    width: 24px;
    height: 24px;
    border-radius: 7px;
    display: inline-flex;
    align-items: center;
    justify-content: center;

    svg {
        width: 0.85rem;
        height: 0.85rem;
    }

    ${({ $tone, theme }) => {
        if ($tone === 'warning') {
            // Deeper amber than the card itself, which is already `warningBg` —
            // matching it here leaves the tile with nothing to read against.
            return css`
                background: ${requireThemeColor(theme, 'warningHoverBg')};
                border: 1px solid ${requireThemeColor(theme, 'warningBorder')};
                color: ${requireThemeColor(theme, 'warningText')};
            `;
        }
        if ($tone === 'danger') {
            return css`
                background: ${requireThemeColor(theme, 'buttonDangerBg')};
                border: 1px solid ${requireThemeColor(theme, 'buttonDangerBorder')};
                color: ${requireThemeColor(theme, 'voteDown')};
            `;
        }
        return css`
            background: ${requireThemeColor(theme, 'accentSubtle')};
            border: 1px solid ${requireThemeColor(theme, 'border')};
            color: ${requireThemeColor(theme, 'subtleText')};
        `;
    }}
`;

const NoticeTitle = styled.div`
    flex: 1;
    min-width: 0;
    font-size: 0.78rem;
    font-weight: 600;
    line-height: 1.25;
    color: ${({ theme }) => requireThemeColor(theme, 'text')};
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
`;

/** Right-aligned headline value (e.g. "95 left", "52 minutes"). */
const NoticeTally = styled.div`
    flex-shrink: 0;
    font-size: 0.68rem;
    font-weight: 600;
    color: ${({ $tone, theme }) => {
        if ($tone === 'danger') return requireThemeColor(theme, 'voteDown');
        if ($tone === 'warning') return requireThemeColor(theme, 'warningText');
        return requireThemeColor(theme, 'subtleText');
    }};
`;

const NoticeBody = styled.div`
    min-width: 0;
    font-size: 0.65rem;
    font-weight: 500;
    line-height: 1.4;
    color: ${({ theme }) => requireThemeColor(theme, 'subtleText')};

    strong {
        color: ${({ theme }) => requireThemeColor(theme, 'text')};
        font-weight: 600;
    }
`;

const QuotaTrack = styled.div`
    width: 100%;
    height: 4px;
    border-radius: 999px;
    overflow: hidden;
    background: ${({ theme }) => requireThemeColor(theme, 'accent')};
`;

const QuotaFill = styled.div`
    height: 100%;
    border-radius: 999px;
    width: ${({ $pct }) => $pct}%;
    background: ${({ $tone, theme }) => ($tone === 'danger'
        ? requireThemeColor(theme, 'voteDown')
        : requireThemeColor(theme, 'gradient'))};
    transition: width 0.2s ease;
`;

/**
 * Compact amber pill, borrowing StatusBadge geometry from `routes/SubscriptionView.js`
 * (999px radius, 0.3rem x 0.7rem, 0.65rem/600) — the action language this page
 * already uses. The shared brand gradient is deliberately not used: it is
 * purple, and on an amber card it reads as a foreign element and outweighs the
 * content it belongs to.
 */
const NoticeAction = styled(Link)`
    align-self: flex-start;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    padding: 0.3rem 0.7rem;
    border-radius: 999px;
    font-size: 0.65rem;
    font-weight: 600;
    font-family: inherit;
    text-decoration: none;
    color: ${({ theme }) => requireThemeColor(theme, 'warningText')};
    background: ${({ theme }) => requireThemeColor(theme, 'warningHoverBg')};
    border: 1px solid ${({ theme }) => requireThemeColor(theme, 'warningBorder')};
    cursor: pointer;
    transition: background 0.15s ease, border-color 0.15s ease;

    &:hover {
        background: ${({ theme }) => requireThemeColor(theme, 'warningBg')};
        border-color: ${({ theme }) => requireThemeColor(theme, 'warningText')};
        color: ${({ theme }) => requireThemeColor(theme, 'warningText')};
        text-decoration: none;
    }

    &:focus-visible {
        outline: 2px solid ${({ theme }) => requireThemeColor(theme, 'focusBlue')};
        outline-offset: 2px;
    }
`;

// A subscription period can be shorter than a day, so rounding everything up to
// whole days reports "1 day" with minutes left on the clock.
export function formatCountdown(targetUnix, now = Date.now()) {
    const ms = targetUnix * 1000 - now;
    if (ms <= 0) return 'any moment';
    const minutes = Math.ceil(ms / 60000);
    if (minutes < 60) return `${minutes} minute${minutes === 1 ? '' : 's'}`;
    const hours = Math.ceil(ms / 3600000);
    if (hours < 24) return `${hours} hour${hours === 1 ? '' : 's'}`;
    const days = Math.ceil(ms / 86400000);
    return `${days} day${days === 1 ? '' : 's'}`;
}

function formatMoment(unix) {
    return new Date(unix * 1000).toLocaleString(undefined, {
        year: 'numeric',
        month: 'short',
        day: 'numeric',
        hour: 'numeric',
        minute: '2-digit',
    });
}

function readStatuses() {
    return {
        quota: Storage.load('daily_quota', null),
        renewal: Storage.load('renewal_warning', null),
    };
}

function validateQuota(value) {
    if (value === null) return null;
    if (!value || !Number.isInteger(value.epoch) || !Number.isInteger(value.used) || !Number.isInteger(value.limit) || !Number.isInteger(value.remaining) || !Number.isInteger(value.reset_at)) {
        throw new Error('Invalid daily_quota status');
    }
    return value;
}

function validateRenewal(value) {
    if (value === null) return null;
    if (!value || !Number.isInteger(value.expiry) || !Number.isInteger(value.next_attempt) || !Number.isInteger(value.last_attempt_epoch) || typeof value.warning_sent !== 'boolean') {
        throw new Error('Invalid renewal_warning status');
    }
    // expiry<=0 is unpaid / admin / cleared schedule — never a real renewal notice
    // (Date(0) renders as 12/31/1969 in US timezones).
    if (value.expiry <= 0) {
        console.debug('[AccountStatusNotices] ignoring non-positive renewal expiry', value);
        return null;
    }
    return value;
}

/**
 * @param {object} props
 * @param {boolean} [props.showQuota=true] — daily no-PoW allowance (Profile / Settings / Subscription)
 * @param {boolean} [props.showRenewal=true] — subscription expiry warning (Home / Subscription)
 */
export default function AccountStatusNotices({ showQuota = true, showRenewal = true } = {}) {
    const [statuses, setStatuses] = useState(readStatuses);
    useEffect(() => {
        const refresh = () => setStatuses(readStatuses());
        window.addEventListener('userStatusUpdated', refresh);
        return () => window.removeEventListener('userStatusUpdated', refresh);
    }, []);
    const quota = showQuota ? validateQuota(statuses.quota) : null;
    const renewal = showRenewal ? validateRenewal(statuses.renewal) : null;
    const renewalDays = renewal ? Math.max(0, Math.ceil((renewal.expiry * 1000 - Date.now()) / 86400000)) : 0;
    const showRenewalNotice = renewal && renewalDays <= 7;
    if (!quota && !showRenewalNotice) return null;
    const quotaExhausted = quota ? quota.remaining === 0 : false;
    const quotaPct = quota && quota.limit > 0
        ? Math.min(100, Math.round((quota.used / quota.limit) * 100))
        : 0;
    return <NoticeList>
        {quota && <NoticeCard role="status" $tone={quotaExhausted ? 'danger' : 'neutral'}>
            <NoticeHeader>
                <NoticeIconTile aria-hidden="true" $tone={quotaExhausted ? 'danger' : 'neutral'}>
                    <HiOutlineBolt />
                </NoticeIconTile>
                <NoticeTitle>Daily no-PoW</NoticeTitle>
                <NoticeTally $tone={quotaExhausted ? 'danger' : 'neutral'}>
                    {quota.remaining.toLocaleString()} left
                </NoticeTally>
            </NoticeHeader>
            <QuotaTrack>
                <QuotaFill $pct={quotaPct} $tone={quotaExhausted ? 'danger' : 'neutral'} />
            </QuotaTrack>
            <NoticeBody>
                <strong>{quota.used.toLocaleString()}</strong> of {quota.limit.toLocaleString()} used
                {' · '}resets in {formatCountdown(quota.reset_at)}
            </NoticeBody>
        </NoticeCard>}
        {showRenewalNotice && <NoticeCard role="alert" $tone="warning">
            <NoticeHeader>
                <NoticeIconTile aria-hidden="true" $tone="warning">
                    <HiOutlineClock />
                </NoticeIconTile>
                <NoticeTitle>Subscription renewal</NoticeTitle>
                <NoticeTally $tone="warning">{formatCountdown(renewal.expiry)}</NoticeTally>
            </NoticeHeader>
            <NoticeBody>Expires {formatMoment(renewal.expiry)}</NoticeBody>
            <NoticeAction to="/subscription">Review renewal</NoticeAction>
        </NoticeCard>}
    </NoticeList>;
}
