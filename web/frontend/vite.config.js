import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

function faqMarkdownPlugin() {
    const faqPath = path.resolve(__dirname, '../../docs/FAQ.md');
    return {
        name: 'mirage-faq-markdown',
        config() {
            if (!fs.existsSync(faqPath)) {
                throw new Error(`FAQ markdown missing at ${faqPath}`);
            }
            const faqMarkdown = fs.readFileSync(faqPath, 'utf8');
            if (!faqMarkdown.trim()) {
                throw new Error(`FAQ markdown empty at ${faqPath}`);
            }
            return {
                define: {
                    __MIRAGE_FAQ_MARKDOWN__: JSON.stringify(faqMarkdown),
                },
            };
        },
    };
}

export default defineConfig(({ mode }) => {
    const env = loadEnv(mode, process.cwd(), '');
    const isProd = mode === 'production';
    const appVersion = env.VITE_APP_VERSION || '';

    if (isProd && !String(appVersion).trim()) {
        throw new Error('VITE_APP_VERSION is required for production builds');
    }

    return {
        plugins: [
            react({
                include: '**/*.{js,jsx}',
            }),
            faqMarkdownPlugin(),
        ],
        define: {
            __MIRAGE_APP_VERSION__: JSON.stringify(isProd ? appVersion : (appVersion || 'dev')),
            global: 'globalThis',
        },
        esbuild: {
            loader: 'jsx',
            include: /src\/.*\.jsx?$/,
            exclude: [],
        },
        resolve: {
            alias: {
                buffer: 'buffer/',
            },
        },
        optimizeDeps: {
            include: ['buffer', 'bip39', '@scure/bip32', '@noble/secp256k1'],
            exclude: ['uvu'],
            esbuildOptions: {
                loader: {
                    '.js': 'jsx',
                },
            },
        },
        server: {
            port: 3000,
            proxy: {
                '/api': 'http://localhost:80',
                '/chain': 'http://localhost:80',
                '/media': 'http://localhost:80',
            },
        },
        preview: {
            port: 4173,
        },
        build: {
            outDir: 'build',
            emptyOutDir: true,
            sourcemap: false,
            rollupOptions: {
                output: {
                    entryFileNames: 'static/js/[name].[hash].js',
                    chunkFileNames: 'static/js/[name].[hash].js',
                    assetFileNames: (assetInfo) => {
                        const name = assetInfo.name || '';
                        if (name.endsWith('.css')) return 'static/css/[name].[hash][extname]';
                        if (/\.(png|jpe?g|gif|svg|webp|ico)$/i.test(name)) {
                            return 'static/media/[name].[hash][extname]';
                        }
                        return 'static/[ext]/[name].[hash][extname]';
                    },
                },
            },
        },
        test: {
            environment: 'jsdom',
            setupFiles: ['./tests/setup.js'],
            include: ['tests/unit/**/*.{test,spec}.{js,jsx}'],
            globals: false,
        },
    };
});
