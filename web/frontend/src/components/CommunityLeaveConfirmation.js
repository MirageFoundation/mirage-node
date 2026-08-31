import { useCallback, useEffect, useRef, useState } from 'react';
import ConfirmDialog from '../themes/default/components/ConfirmDialog';
import { communityLabel } from '../utils/community';
import { registerCommunityLeaveConfirmationHandler } from '../utils/communityLeaveConfirmation';

export default function CommunityLeaveConfirmation() {
    const [request, setRequest] = useState(null);
    const pendingRef = useRef(null);

    const finish = useCallback((confirmed) => {
        const pending = pendingRef.current;
        pendingRef.current = null;
        setRequest(null);
        if (pending) pending.resolve(confirmed);
    }, []);

    const handleRequest = useCallback((details) => {
        if (pendingRef.current) {
            return Promise.reject(new Error('Community leave confirmation is already open'));
        }
        return new Promise((resolve) => {
            pendingRef.current = { resolve };
            setRequest(details);
        });
    }, []);

    useEffect(() => {
        const unregister = registerCommunityLeaveConfirmationHandler(handleRequest);
        return () => {
            unregister();
            const pending = pendingRef.current;
            pendingRef.current = null;
            if (pending) pending.resolve(false);
        };
    }, [handleRequest]);

    if (!request) return null;

    const name = communityLabel(request.community);
    const { isLeader, memberCount, teamName } = request.membership;
    const message = memberCount === 1
        ? `Leaving ${name} will also leave and permanently delete curator team “${teamName}” because you are its last curator.`
        : isLeader
            ? `Leaving ${name} will also leave curator team “${teamName}” and transfer leadership to its longest-serving remaining curator.`
            : `Leaving ${name} will also remove you from curator team “${teamName}”.`;

    return (
        <ConfirmDialog
            open
            title={`Leave ${name}?`}
            message={message}
            confirmLabel="Leave community"
            confirmVariant="danger"
            onConfirm={() => finish(true)}
            onCancel={() => finish(false)}
        />
    );
}
