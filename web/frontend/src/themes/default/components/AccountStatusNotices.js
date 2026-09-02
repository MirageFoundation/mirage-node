import { useEffect, useState } from 'react';
import styled from 'styled-components';
import { Link } from 'react-router-dom';
import { HiOutlineClock } from 'react-icons/hi2';
import Storage from '../../../utils/Storage';
import { requireThemeColor } from '../../../utils/themeColor';

/**
 * Account status notices — `default` theme.
 *
 * The quota is a plain `label: value` row, matching the `Balance:` field rows it
 * sits beside on Profile / Settings / Subscription. It is ambient information,
 * not something to act on, so it gets no card, icon or meter.
 *
 * The renewal warning is the one notice that needs attention, so it is a hero
 * card: `bg` with a 1px border and 8px radius (R1/R3) using the canonical amber
 * warning pair (R2 `warning*`), on the compact type scale (R7 — 0.78rem/600
 * title, 0.68rem/600 tally, 0.65rem body, 0.65rem/600 action pill). Geometry
 * mirrors the app-download and NSFW consent heroes in `routes/MainView.js`; the
 * action pill follows SubscriptionView's StatusBadge.
 */

// Each notice owns its own spacing: the quota is a field row that has to sit on
// the host's row rhythm, while the card is an inset block. A shared wrapper
// margin would double up with the quota's row padding and push it out of line
// with the `Balance:` row above it.
const NoticeList = styled.div`
    display: flex;
    flex-direction: column;
`;

/* Plain label:value row for the quota. Geometry is copied from ProfileView's
 * `ProfileFieldRow` so this row is indistinguishable from `Balance:` — same
 * label column, same gap, same padding at every breakpoint. */
const QuotaRow = styled.div`
    display: grid;
    grid-template-columns: 150px minmax(0, 1fr);
    gap: 1rem;
    align-items: center;
    padding: 0.55rem 1rem;
    box-sizing: border-box;
    width: 100%;
    min-width: 0;
    color: ${({ theme }) => requireThemeColor(theme, 'subtleText')};
    font-size: 0.72rem;
    font-weight: 500;
    line-height: 1.3;

    @media (max-width: 1000px) {
        padding: 0.5rem 0.85rem;
    }

    @media (max-width: 600px) {
        grid-template-columns: minmax(0, 1fr);
        gap: 0.2rem;
        padding: 0.5rem 0;
    }
`;

const QuotaLabel = styled.div`
    font-weight: 500;
    color: ${({ theme, $exhausted }) => requireThemeColor(theme, $exhausted ? 'voteDown' : 'text')};
`;

const QuotaValue = styled.div`
    min-width: 0;
`;

// Full width with its own 1rem padding, like every other card in this column
// (CardView, NsfwWelcomeHero, CreatorEarningsBanner). The host supplies the
// gutter: FeedHeroColumn has none, so the card edge lines up with the posts
// below, and SectionBody's `0 1rem` insets it on Subscription / Settings /
// Profile. Adding a margin here as well double-insets it in SectionBody and
// pushes the text to 2rem, out of line with the heading above it.
const NoticeCard = styled.div`
    box-sizing: border-box;
    width: 100%;
    align-self: flex-start;
    margin: 4px 0;
    border-radius: 8px;
    padding: 0.7rem 1rem 0.75rem;
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
    background: ${({ theme }) => requireThemeColor(theme, 'warningBg')};
    border: 1px solid ${({ theme }) => requireThemeColor(theme, 'warningBorder')};

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

// Deeper amber than the card itself, which is already `warningBg` — matching it
// here leaves the tile with nothing to read against.
const NoticeIconTile = styled.span`
    flex-shrink: 0;
    width: 24px;
    height: 24px;
    border-radius: 7px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    background: ${({ theme }) => requireThemeColor(theme, 'warningHoverBg')};
    border: 1px solid ${({ theme }) => requireThemeColor(theme, 'warningBorder')};
    color: ${({ theme }) => requireThemeColor(theme, 'warningText')};

    svg {
        width: 0.85rem;
        height: 0.85rem;
    }
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

/** Right-aligned headline value (e.g. "52 minutes"). */
const NoticeTally = styled.div`
    flex-shrink: 0;
    font-size: 0.68rem;
    font-weight: 600;
    color: ${({ theme }) => requireThemeColor(theme, 'warningText')};
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
    return <NoticeList>
        {quota && <QuotaRow role="status">
            <QuotaLabel $exhausted={quota.remaining === 0}>Daily no-PoW:</QuotaLabel>
            <QuotaValue>
                {quota.used.toLocaleString()} of {quota.limit.toLocaleString()} used
            </QuotaValue>
        </QuotaRow>}
        {showRenewalNotice && <NoticeCard role="alert">
            <NoticeHeader>
                <NoticeIconTile aria-hidden="true">
                    <HiOutlineClock />
                </NoticeIconTile>
                <NoticeTitle>Subscription renewal</NoticeTitle>
                <NoticeTally>{formatCountdown(renewal.expiry)}</NoticeTally>
            </NoticeHeader>
            <NoticeBody>Expires {formatMoment(renewal.expiry)}</NoticeBody>
            <NoticeAction to="/subscription">Review renewal</NoticeAction>
        </NoticeCard>}
    </NoticeList>;
}
