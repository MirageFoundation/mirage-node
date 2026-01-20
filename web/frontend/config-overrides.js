const webpack = require('webpack');

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
    ]);
    // Ignore uvu (test runner) that gets pulled in by remark-gfm dependencies
    // Replace process/browser imports to use the fallback resolution
    config.plugins = (config.plugins || []).concat([
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
    return config;
};
