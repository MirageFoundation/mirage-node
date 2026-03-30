let notifier = null;

export function setNotifier(fn) {
    notifier = typeof fn === 'function' ? fn : null;
}

export function updateNotification(message, timeout = 0.5, alert = false) {
    if (typeof notifier === 'function') {
        try {
            notifier(message, timeout, alert);
        } catch (_) { /* no-op */ }
    }
}


