import React, { useState, useEffect, useCallback, useRef } from 'react';
import styled, { keyframes } from 'styled-components';
import { setNotifier } from '../../../utils/notifications';

const slideIn = keyframes`
    from {
        transform: translateY(-100%);
        opacity: 0;
    }
    to {
        transform: translateY(0);
        opacity: 1;
    }
`;

const slideOut = keyframes`
    from {
        transform: translateY(0);
        opacity: 1;
    }
    to {
        transform: translateY(-100%);
        opacity: 0;
    }
`;

const ToastContainer = styled.div`
    position: fixed;
    top: 0.75rem;
    left: 50%;
    transform: translateX(-50%);
    z-index: 10000;
    pointer-events: none;
`;

const ToastItem = styled.div`
    background: ${({ alert }) =>
        alert
            ? 'rgba(220, 38, 38, 0.95)'
            : 'linear-gradient(135deg, rgba(88, 86, 214, 0.95) 0%, rgba(130, 87, 229, 0.95) 100%)'};
    color: #fff;
    border: 1px solid ${({ alert }) =>
        alert
            ? 'rgba(220, 38, 38, 0.6)'
            : 'rgba(130, 87, 229, 0.5)'};
    border-radius: 8px;
    padding: 0.5rem 0.9rem;
    font-size: 0.8rem;
    font-weight: 600;
    box-shadow: 0 4px 16px rgba(88, 86, 214, 0.4);
    pointer-events: auto;
    animation: ${({ exiting }) => exiting ? slideOut : slideIn} 0.2s ease-out forwards;
    display: flex;
    align-items: center;
    gap: 0.5rem;
    white-space: nowrap;
`;

const Spinner = styled.div`
    width: 12px;
    height: 12px;
    border-radius: 50%;
    border: 2px solid rgba(255, 255, 255, 0.3);
    border-top-color: #fff;
    animation: toast-spin 0.8s linear infinite;
    flex-shrink: 0;

    @keyframes toast-spin {
        0% { transform: rotate(0deg); }
        100% { transform: rotate(360deg); }
    }
`;

// Check if message is a progress update (should replace existing toast)
function isProgressMessage(msg) {
    const lower = (msg || '').toLowerCase();
    return lower.includes('pow') ||
        lower.includes('solving') ||
        lower.includes('submitting') ||
        lower.includes('performing') ||
        lower.includes('fetching') ||
        lower.includes('preparing');
}

function Toast() {
    const [toast, setToast] = useState(null);
    const timeoutRef = useRef(null);

    const showToast = useCallback((message, timeout = 0.5, alert = false) => {
        // Clear any pending timeout
        if (timeoutRef.current) {
            clearTimeout(timeoutRef.current);
            timeoutRef.current = null;
        }

        const showSpinner = isProgressMessage(message);

        // Update or create toast (only one at a time)
        setToast({ message, alert, showSpinner, exiting: false });

        if (timeout > 0) {
            timeoutRef.current = setTimeout(() => {
                setToast(prev => prev ? { ...prev, exiting: true } : null);
                setTimeout(() => setToast(null), 200);
            }, timeout * 1000);
        }
    }, []);

    useEffect(() => {
        setNotifier(showToast);
        return () => {
            setNotifier(null);
            if (timeoutRef.current) clearTimeout(timeoutRef.current);
        };
    }, [showToast]);

    if (!toast) return null;

    return (
        <ToastContainer>
            <ToastItem alert={toast.alert} exiting={toast.exiting}>
                {toast.showSpinner && <Spinner />}
                {toast.message}
            </ToastItem>
        </ToastContainer>
    );
}

export default Toast;

