/**
 * Vitest setup — browser API stubs shared by unit tests.
 */
import { webcrypto } from 'node:crypto';

if (!globalThis.crypto) {
    globalThis.crypto = webcrypto;
}

const store = new Map();
const localStorageMock = {
    getItem: (k) => (store.has(String(k)) ? store.get(String(k)) : null),
    setItem: (k, v) => { store.set(String(k), String(v)); },
    removeItem: (k) => { store.delete(String(k)); },
    clear: () => { store.clear(); },
    key: (i) => [...store.keys()][i] ?? null,
    get length() { return store.size; },
};

Object.defineProperty(globalThis, 'localStorage', {
    value: localStorageMock,
    configurable: true,
});

if (typeof window !== 'undefined') {
    Object.defineProperty(window, 'localStorage', {
        value: localStorageMock,
        configurable: true,
    });
}
