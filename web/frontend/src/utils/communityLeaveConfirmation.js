let confirmationHandler = null;

export function registerCommunityLeaveConfirmationHandler(handler) {
    if (confirmationHandler) {
        throw new Error('Community leave confirmation handler is already registered');
    }
    confirmationHandler = handler;
    return () => {
        if (confirmationHandler === handler) confirmationHandler = null;
    };
}

export function requestCommunityLeaveConfirmation(details) {
    if (!confirmationHandler) {
        throw new Error('Community leave confirmation handler is not registered');
    }
    return confirmationHandler(details);
}
