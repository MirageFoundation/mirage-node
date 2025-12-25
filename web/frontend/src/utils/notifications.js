let notifier = null;

export function setNotifier(fn) {
    notifier = typeof fn === 'function' ? fn : null;
}

export function updateNotification(message, timeout = 3.0, alert = false) {
    if (typeof notifier === 'function') {
        try {
            notifier(message, timeout, alert);
        } catch (_) { /* no-op */ }
    }
}


