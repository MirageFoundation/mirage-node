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
    background: ${({ alert, theme }) =>
        alert ? theme.colors.danger : theme.colors.panel};
    color: ${({ alert, theme }) =>
        alert ? theme.colors.bg : theme.colors.text};
    border: 1px solid ${({ alert, theme }) =>
        alert ? theme.colors.dangerBorder : theme.colors.border};
    border-radius: 4px;
    padding: 0.5rem 0.9rem;
    font-size: 0.8rem;
    font-weight: 600;
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
    border: 2px solid ${({ theme }) => theme.colors.border};
    border-top-color: ${({ theme }) => theme.colors.text};
    animation: toast-spin 0.8s linear infinite;
    flex-shrink: 0;

    @keyframes toast-spin {
        0% { transform: rotate(0deg); }
        100% { transform: rotate(360deg); }
    }
`;

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
        if (timeoutRef.current) {
            clearTimeout(timeoutRef.current);
            timeoutRef.current = null;
        }

        const showSpinner = isProgressMessage(message);
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
