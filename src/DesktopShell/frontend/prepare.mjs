import { build } from 'vite';
import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

// One in-memory document: no listener, output directory or frontend service.
const root = fileURLToPath(new URL('./', import.meta.url));
const result = await build({
    root, configFile: false, publicDir: false, logLevel: 'silent',
    define: { 'process.env.NODE_ENV': JSON.stringify('production') },
    build: {
        write: false, sourcemap: false, cssCodeSplit: false, modulePreload: false, minify: true,
        assetsInlineLimit: () => true,
        lib: { entry: path.join(root, 'src/main.tsx'), name: 'QQBotDesktop', formats: ['iife'] },
    },
});
const outputs = (Array.isArray(result) ? result : [result]).flatMap(item => item.output);
const script = outputs.filter(item => item.type === 'chunk');
const styles = outputs.filter(item => item.type === 'asset' && item.fileName.endsWith('.css'));
if (script.length !== 1 || outputs.length !== script.length + styles.length) throw Error('Unexpected external frontend assets');
let html = await fs.readFile(path.join(root, 'index.html'), 'utf8');
const icon = await fs.readFile(path.join(root, 'public/qqbot.svg'));
html = html.replace('href="/qqbot.svg"', () => `href="data:image/svg+xml;base64,${icon.toString('base64')}"`)
    .replace('</head>', () => `<style>${styles.map(item => String(item.source)).join('\n').replace(/<\/style/gi, '<\\/style')}</style></head>`)
    .replace('<script type="module" src="/src/main.tsx"></script>', () => `<script>${script[0].code.replace(/<\/script/gi, '<\\/script')}</script>`);
// WebView2 NavigateToString has a 2 MiB limit; leave room for startup metadata.
if (Buffer.byteLength(html, 'utf8') > 1500000 || html.includes('src="/src/')) throw Error(`Frontend document is too large or incomplete (${Buffer.byteLength(html)} bytes)`);
process.stdout.write(JSON.stringify({ html }) + '\n');
