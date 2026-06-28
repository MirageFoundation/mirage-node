const webpack = require('webpack');
const fs = require('fs');
const path = require('path');

// Suppress source map generation to avoid noisy warnings from dependencies
process.env.GENERATE_SOURCEMAP = 'false';

// Mock localStorage for Node.js build environment (before any code tries to access it)
const mockLocalStorage = {
    getItem: () => null,
    setItem: () => { },
    removeItem: () => { },
    clear: () => { },
    key: () => null,
    length: 0,
};

if (typeof window === 'undefined') {
    global.window = global.window || {};
    global.window.localStorage = mockLocalStorage;
}

// Also mock at global level for Node.js internal webstorage
if (typeof global !== 'undefined') {
    Object.defineProperty(global, 'localStorage', {
        get: () => mockLocalStorage,
        configurable: true,
    });
}

module.exports = function override(config) {
    const faqMarkdown = fs.readFileSync(path.resolve(__dirname, '../../docs/FAQ.md'), 'utf8');

    // Configure HtmlWebpackPlugin to not evaluate code that might access localStorage
    const htmlWebpackPlugin = config.plugins.find(
        plugin => plugin.constructor.name === 'HtmlWebpackPlugin'
    );
    if (htmlWebpackPlugin) {
        htmlWebpackPlugin.options = htmlWebpackPlugin.options || {};
        htmlWebpackPlugin.options.templateParameters = htmlWebpackPlugin.options.templateParameters || {};
        // Disable template evaluation that might trigger localStorage access
        if (htmlWebpackPlugin.options.templateParameters.compilation) {
            htmlWebpackPlugin.options.templateParameters.compilation = undefined;
        }
    }
    // Minimal webpack fallback for browser build compatibility
    config.resolve = config.resolve || {};
    config.resolve.fallback = {
        ...(config.resolve.fallback || {}),
        crypto: require.resolve('crypto-browserify'),
        stream: require.resolve('stream-browserify'),
        buffer: require.resolve('buffer/'),
        process: require.resolve('process/browser'),
    };
    config.module = config.module || {};
    config.module.rules = (config.module.rules || []).concat([
        {
            test: /@cosmjs\/(crypto|encoding|math|utils)\/build\/.+\.js$/,
            enforce: 'pre',
            use: [
                {
                    loader: require.resolve('source-map-loader'),
                    options: { filterSourceMappingUrl: () => false },
                },
            ],
        },
        // Allow extensionless ESM imports (e.g. 'process/browser') that webpack 5
        // otherwise rejects under fullySpecified resolution.
        {
            test: /\.m?js$/,
            resolve: { fullySpecified: false },
        },
    ]);
    // Ignore uvu (test runner) that gets pulled in by remark-gfm dependencies
    // Replace process/browser imports to use the fallback resolution
    config.plugins = (config.plugins || []).concat([
        new webpack.DefinePlugin({
            __MIRAGE_FAQ_MARKDOWN__: JSON.stringify(faqMarkdown),
        }),
        new webpack.IgnorePlugin({
            resourceRegExp: /^uvu$/,
            contextRegExp: /node_modules/,
        }),
        // Provide Buffer and process globally for Solana web3.js
        new webpack.ProvidePlugin({
            Buffer: ['buffer', 'Buffer'],
            process: 'process/browser',
        }),
    ]);
    // CRA's eslint-webpack-plugin caches to node_modules/.cache/.eslintcache. After large refactors,
    // that cache can serve stale rule results (wrong line numbers, imports that no longer exist).
    for (const plugin of config.plugins || []) {
        if (plugin && plugin.constructor && plugin.constructor.name === 'ESLintWebpackPlugin' && plugin.options) {
            plugin.options.cache = false;
        }
    }
    return config;
};
