import './registry/bootstrapThemeId';
import React from 'react';
import { createRoot } from 'react-dom/client';
import { Buffer } from 'buffer';
import App from './App';

// Minimal Buffer polyfill required by bip39 / HD key libs in the browser.
if (typeof window !== 'undefined') {
    if (typeof window.Buffer === 'undefined') {
        window.Buffer = Buffer;
    }
    if (typeof window.global === 'undefined') {
        window.global = window;
    }
}

const container = document.getElementById('root');
const root = createRoot(container);
root.render(<App />);