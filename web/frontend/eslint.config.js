import js from '@eslint/js';
import react from 'eslint-plugin-react';
import reactHooks from 'eslint-plugin-react-hooks';
import globals from 'globals';

export default [
    {
        ignores: [
            'build/**',
            'node_modules/**',
            'public/pow/argon2-bundled.min.js',
            '.repro-build-a/**',
            '.repro-build-b/**',
        ],
    },
    js.configs.recommended,
    {
        files: ['src/**/*.{js,jsx}', 'tests/**/*.{js,jsx}'],
        languageOptions: {
            ecmaVersion: 2022,
            sourceType: 'module',
            globals: {
                ...globals.browser,
                ...globals.es2021,
                __MIRAGE_FAQ_MARKDOWN__: 'readonly',
                __MIRAGE_APP_VERSION__: 'readonly',
            },
            parserOptions: {
                ecmaFeatures: { jsx: true },
            },
        },
        plugins: {
            react,
            'react-hooks': reactHooks,
        },
        settings: {
            react: { version: 'detect' },
        },
        rules: {
            ...react.configs.recommended.rules,
            ...reactHooks.configs.recommended.rules,
            'react/react-in-jsx-scope': 'off',
            'react/prop-types': 'off',
            'no-unused-vars': ['warn', {
                argsIgnorePattern: '^_',
                varsIgnorePattern: '^_',
                caughtErrorsIgnorePattern: '^_',
            }],
            'no-empty': ['error', { allowEmptyCatch: true }],
            'no-restricted-globals': ['error', 'event', 'fdescribe'],
        },
    },
    {
        files: ['scripts/**/*.{js,mjs}', 'vite.config.js', 'playwright.config.js'],
        languageOptions: {
            ecmaVersion: 2022,
            sourceType: 'module',
            globals: {
                ...globals.node,
            },
        },
        rules: {
            'no-unused-vars': ['warn', { argsIgnorePattern: '^_' }],
        },
    },
    {
        files: ['public/pow/worker.js'],
        languageOptions: {
            ecmaVersion: 2022,
            sourceType: 'script',
            globals: {
                ...globals.worker,
                argon2: 'readonly',
                importScripts: 'readonly',
            },
        },
    },
];
