import { useEffect, useState } from 'react';
import styled from 'styled-components';
import { Link } from 'react-router-dom';
import Storage from '../../../utils/Storage';
import { requireThemeColor } from '../../../utils/themeColor';

const NoticeList = styled.div`
    margin: 0.25rem 1rem;

    @media (max-width: 1000px) {
        margin: 0.25rem 0.85rem;
    }

    @media (max-width: 600px) {
        margin: 0.25rem 0;
    }
`;

const Notice = styled.div`
    display: grid;
    grid-template-columns: 150px minmax(0, 1fr);
    gap: 1rem;
    align-items: center;
    padding: 0.55rem 0;
    color: ${({ theme }) => requireThemeColor(theme, 'subtleText')};
    font-size: 0.72rem;
    font-weight: 500;
    line-height: 1.4;

    & + & {
        border-top: 1px solid ${({ theme }) => requireThemeColor(theme, 'borderSubtle')};
    }

    @media (max-width: 600px) {
        grid-template-columns: 1fr;
        gap: 0.1rem;
    }
`;

const NoticeLabel = styled.div`
    color: ${({ theme, $tone }) => {
        if ($tone === 'danger') return requireThemeColor(theme, 'voteDown');
        if ($tone === 'warning') return requireThemeColor(theme, 'inboxHighlightRail');
        return requireThemeColor(theme, 'text');
    }};
    font-weight: ${({ $regular }) => ($regular ? 500 : 600)};
`;

const NoticeBody = styled.div`
    min-width: 0;

    strong {
        color: ${({ theme }) => requireThemeColor(theme, 'text')};
        font-weight: 600;
    }
`;

const NoticeLink = styled(Link)`
    color: ${({ theme }) => requireThemeColor(theme, 'link')};
    font-weight: 600;
    text-decoration: none;

    &:hover {
        color: ${({ theme }) => requireThemeColor(theme, 'linkHover')};
    }
`;

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
        {quota && <Notice role="status">
            <NoticeLabel $regular $tone={quota.remaining === 0 ? 'danger' : undefined}>Daily no-PoW:</NoticeLabel>
            <NoticeBody>
                {quota.used.toLocaleString()} of {quota.limit.toLocaleString()} used
            </NoticeBody>
        </Notice>}
        {showRenewalNotice && <Notice role="alert">
            <NoticeLabel $tone="warning">Subscription renewal:</NoticeLabel>
            <NoticeBody>
                Expires in <strong>{renewalDays} day{renewalDays === 1 ? '' : 's'}</strong>
                {' · '}{new Date(renewal.expiry * 1000).toLocaleString()}
                {' · '}<NoticeLink to="/subscription">Review renewal</NoticeLink>
            </NoticeBody>
        </Notice>}
    </NoticeList>;
}
