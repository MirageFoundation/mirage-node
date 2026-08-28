import { useEffect, useState } from 'react';
import styled from 'styled-components';
import { Link } from 'react-router-dom';
import Storage from '../../../utils/Storage';
import { requireThemeColor } from '../../../utils/themeColor';

const Notice = styled.div`
    padding: 0.65rem 0.8rem;
    margin: 0.5rem 0;
    border: 1px solid ${({ theme, $warning }) => $warning
        ? requireThemeColor(theme, 'buttonDangerBorder')
        : requireThemeColor(theme, 'border')};
    border-radius: 8px;
    background: ${({ theme }) => requireThemeColor(theme, 'panel')};
    color: ${({ theme }) => requireThemeColor(theme, 'text')};
    font-size: 0.72rem;
    line-height: 1.45;
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
    return value;
}

export default function AccountStatusNotices() {
    const [statuses, setStatuses] = useState(readStatuses);
    useEffect(() => {
        const refresh = () => setStatuses(readStatuses());
        window.addEventListener('userStatusUpdated', refresh);
        return () => window.removeEventListener('userStatusUpdated', refresh);
    }, []);
    const quota = validateQuota(statuses.quota);
    const renewal = validateRenewal(statuses.renewal);
    const renewalDays = renewal ? Math.max(0, Math.ceil((renewal.expiry * 1000 - Date.now()) / 86400000)) : 0;
    return <>
        {quota && <Notice $warning={quota.remaining === 0} role="status">
            Daily sponsored actions: <strong>{quota.used} / {quota.limit}</strong> used, {quota.remaining} remaining.
            Resets {new Date(quota.reset_at * 1000).toLocaleString()}.
        </Notice>}
        {renewal && <Notice $warning role="alert">
            Your subscription expires in {renewalDays} day{renewalDays === 1 ? '' : 's'} ({new Date(renewal.expiry * 1000).toLocaleString()}).
            {' '}<Link to="/subscription">Review renewal</Link>
        </Notice>}
    </>;
}
