import { useCallback, useEffect, useRef, useState } from 'react';
import { updateNotification } from '../utils/notifications';
import { CURATION_MODE, LENS, requireCommunitySlug } from '../utils/curation';

/**
 * Lens choice is view-only in the client. Changing the dropdown must never
 * broadcast a chain tx — feed filtering already goes through ?lens= query params.
 */
export function useCurationPreference(community, detail) {
    const slug = requireCommunitySlug(community);
    const [error, setError] = useState('');
    const staleToastShown = useRef(false);

    useEffect(() => {
        const storedMode = detail?.stored_mode;
        const effectiveMode = detail?.effective_mode;
        if (
            storedMode === CURATION_MODE.PINNED
            && effectiveMode === CURATION_MODE.LIVE_DEFAULT
            && !staleToastShown.current
        ) {
            staleToastShown.current = true;
            updateNotification('That team is no longer available; showing the team with the most subscribers.', 6, true);
            console.debug('[lens] stale team selection resolved to most-subscribed team', { community: slug });
        }
    }, [detail, slug]);

    const selectLens = useCallback(async (lens, teamId = null) => {
        let pinnedTeamId = null;
        if (lens === LENS.TEAM) {
            pinnedTeamId = Number(teamId);
            if (!Number.isSafeInteger(pinnedTeamId) || pinnedTeamId <= 0) {
                throw new Error('team lens requires a team id');
            }
        } else if (lens !== LENS.DEFAULT && lens !== LENS.RAW) {
            throw new Error(`Cannot select lens: ${lens}`);
        }
        setError('');
        console.debug('[lens] selecting locally (no tx)', { community: slug, lens, teamId: pinnedTeamId });
        window.dispatchEvent(new CustomEvent('lensChanged', {
            detail: { community: slug, lens, teamId: pinnedTeamId },
        }));
        return { success: true };
    }, [slug]);

    return {
        selectLens,
        pending: false,
        pendingStatus: '',
        error,
    };
}

export default useCurationPreference;
