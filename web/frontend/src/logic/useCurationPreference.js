import { useCallback, useEffect, useRef, useState } from 'react';
import * as tx from '../utils/tx';
import { updateNotification } from '../utils/notifications';
import { CURATION_MODE, LENS, invalidateCurationReads, requireCommunitySlug } from '../utils/curation';
import { formatError } from '../utils/errorMessages';
import { usePendingCuration } from './usePendingCuration';

export function useCurationPreference(community, detail) {
    const slug = requireCommunitySlug(community);
    const [error, setError] = useState('');
    const staleToastShown = useRef(false);
    const { getInfo, getStatus } = usePendingCuration();
    const pending = getInfo('set_curation_preference', slug, 0, '');

    useEffect(() => {
        const storedMode = detail?.stored_mode;
        const effectiveMode = detail?.effective_mode;
        if (
            storedMode === CURATION_MODE.PINNED
            && effectiveMode === CURATION_MODE.LIVE_DEFAULT
            && !staleToastShown.current
        ) {
            staleToastShown.current = true;
            updateNotification('That team is no longer available; showing the node default.', 6, true);
            console.debug('[lens] stale team selection resolved to default', { community: slug });
        }
    }, [detail, slug]);

    const selectLens = useCallback(async (lens, teamId = null) => {
        let mode;
        let pinnedTeamId = 0;
        if (lens === LENS.DEFAULT) mode = CURATION_MODE.LIVE_DEFAULT;
        else if (lens === LENS.RAW) mode = CURATION_MODE.RAW;
        else if (lens === LENS.TEAM) {
            mode = CURATION_MODE.PINNED;
            pinnedTeamId = Number(teamId);
        } else {
            throw new Error(`Cannot persist lens: ${lens}`);
        }
        setError('');
        console.debug('[lens] selecting', { community: slug, lens, teamId: pinnedTeamId || null });
        const result = await tx.setCurationPreference(slug, mode, pinnedTeamId);
        if (!result?.success) {
            const message = formatError(result);
            setError(message);
            throw new Error(message);
        }
        invalidateCurationReads(slug);
        window.dispatchEvent(new CustomEvent('lensChanged', {
            detail: { community: slug, lens, teamId: pinnedTeamId || null },
        }));
        return result;
    }, [slug]);

    return {
        selectLens,
        pending: !!pending,
        pendingStatus: getStatus('set_curation_preference', slug, 0, '', 'Changing lens…'),
        error,
    };
}

export default useCurationPreference;
