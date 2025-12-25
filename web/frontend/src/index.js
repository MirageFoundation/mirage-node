import React from 'react';
import ReactDOM from 'react-dom';
import App from './App';
// BrowserRouter is configured inside App

// Minimal polyfills for Node globals required by some libs (e.g., bip39)
try {
    if (typeof window !== 'undefined') {
        if (typeof window.Buffer === 'undefined') {
            const { Buffer } = require('buffer');
            window.Buffer = Buffer;
        }
        if (typeof window.process === 'undefined') {
            window.process = require('process/browser');
        }
        if (typeof window.global === 'undefined') {
            window.global = window;
        }
    }
} catch (_) { /* ignore */ }

ReactDOM.render(
    <React.StrictMode>
        <App />
    </React.StrictMode>,
    document.getElementById('root'))