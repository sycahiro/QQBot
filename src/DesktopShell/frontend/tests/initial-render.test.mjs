// Exercise the pre-bridge/empty-data render before asynchronous desktop calls.
// This catches null dereferences that only occur while changing pages.
import test from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { createServer } from 'vite';

test('business pages render while the bridge and records are still loading', async () => {
    const server = await createServer({
        root: fileURLToPath(new URL('..', import.meta.url)),
        configFile: false,
        appType: 'custom',
        cacheDir: fileURLToPath(new URL('../../node_modules/.cache/render-tests', import.meta.url)),
        optimizeDeps: { noDiscovery: true },
        server: { middlewareMode: true, hmr: false, watch: null },
    });
    try {
        const pages = [
            ['/src/settings/storage.tsx', 'StorageSettings'],
            ['/src/agent/sessions.tsx', 'Sessions'],
            ['/src/agent/archive.tsx', 'Archive'],
            ['/src/agent/memory.tsx', 'Memory'],
            ['/src/agent/settings.tsx', 'BotSettings'],
            ['/src/agent/extensions.tsx', 'Extensions'],
            ['/src/agent/market.tsx', 'Market'],
            ['/src/agent/stickers.tsx', 'Stickers'],
            ['/src/residence.tsx', 'ResidenceSettings'],
            ['/src/settings/media.tsx', 'MediaSettings'],
            ['/src/diagnostics.tsx', 'Logs'],
            ['/src/diagnostics.tsx', 'Diagnostics'],
            ['/src/qq.tsx', 'QqAccounts'],
        ];
        for (const [path, name] of pages) {
            const module = await server.ssrLoadModule(path);
            for (const ready of [false, true]) {
                const html = renderToStaticMarkup(
                    React.createElement(module[name], {
                        ready,
                        account: '12345678',
                        onBack: () => {},
                    }),
                );
                assert.ok(html.length > 0, `${name} should render before any bridge response`);
                assert.ok(!html.includes('界面暂时无法显示'));
            }
        }
        const { AgentWorkspace } = await server.ssrLoadModule('/src/agent/index.tsx');
        const { SystemSettings } = await server.ssrLoadModule('/src/settings/index.tsx');
        const settings = renderToStaticMarkup(
            React.createElement(SystemSettings, { info: null, theme: 'light', setTheme: () => {} }),
        );
        for (const label of ['通用', '模型 API', '图片处理', '联网', '关于'])
            assert.ok(settings.includes(label));
        const { Configuration } = await server.ssrLoadModule('/src/settings/configuration.tsx');
        assert.ok(
            renderToStaticMarkup(
                React.createElement(Configuration, { ready: true, scope: 'global' }),
            ).includes('正在读取全局设置'),
        );
        const { NetworkSettings } = await server.ssrLoadModule('/src/settings/network.tsx');
        assert.ok(
            renderToStaticMarkup(React.createElement(NetworkSettings, { ready: true })).includes(
                '正在读取联网设置',
            ),
        );
        const offline = renderToStaticMarkup(
            React.createElement(AgentWorkspace, {
                ready: true,
                status: null,
                connection: {
                    state: 'idle',
                    connected: false,
                    account: { uin: '12345678', pid: 1 },
                },
                onStatus: () => {},
                onConnect: () => {},
            }),
        );
        // 连接入口集中在「连接」页：工作区页未连接时只提示去哪里连接。
        assert.ok(offline.includes('请先在「连接」页连接个人 QQ'));
        assert.ok(offline.includes('前往连接页'));
        assert.ok(!offline.includes('已打开的 QQ'));
        assert.ok(!offline.includes('agent-tabs'));
        const online = renderToStaticMarkup(
            React.createElement(AgentWorkspace, {
                ready: true,
                status: null,
                connection: {
                    state: 'ready',
                    connected: true,
                    account: { uin: '12345678', pid: 1, nickname: '个人 QQ', version: null },
                    error: null,
                },
                onStatus: () => {},
                onConnect: () => {},
            }),
        );
        assert.ok(online.includes('agent-tabs') && !online.includes('请先在「连接」页连接个人 QQ'));
        const { DebugTools } = await server.ssrLoadModule('/src/debug-tools.tsx');
        for (const state of ['idle', 'connecting', 'error']) {
            const props = {
                ready: true,
                connection: { state, connected: false, account: { uin: '12345678', pid: 1 } },
            };
            const html = renderToStaticMarkup(React.createElement(DebugTools, props));
            assert.ok(
                html.includes(
                    state === 'connecting' ? '正在连接个人 QQ' : '请先在「连接」页连接个人 QQ',
                ),
            );
            assert.ok(
                !html.includes('调试接口') &&
                    !html.includes('执行接口') &&
                    !html.includes('消息构建</button>'),
            );
        }
        const { ConnectionBoundary } = await server.ssrLoadModule(
            '/src/components/connection-boundary.tsx',
        );
        for (const connection of [
            null,
            { state: 'ready', connected: true, account: null },
            { state: 'connecting', connected: false, account: { uin: '12345678', pid: 1 } },
        ]) {
            let calls = 0;
            renderToStaticMarkup(
                React.createElement(
                    ConnectionBoundary,
                    { ready: true, connection, description: 'test', icon: null },
                    () => {
                        calls++;
                        return 'private';
                    },
                ),
            );
            assert.equal(calls, 0, 'unverified connection must never mount account children');
        }
        const { Select } = await server.ssrLoadModule('/src/components/select.tsx');
        for (const editable of [false, true]) {
            const html = renderToStaticMarkup(
                React.createElement(Select, {
                    label: '模型名称',
                    value: 'test-model',
                    options: [{ value: 'test-model', label: 'test-model' }],
                    onChange: () => {},
                    editable,
                }),
            );
            assert.ok(html.includes('role="combobox"') && html.includes('aria-expanded="false"'));
            assert.ok(!html.includes('<select') && !html.includes('<datalist'));
            assert.ok(html.includes(editable ? '<input' : 'ui-select-trigger'));
        }
        const { ArchiveMessage } = await server.ssrLoadModule('/src/agent/archive-message.tsx');
        for (const self of [false, true]) {
            const item = {
                id: 1,
                mid: '1',
                ts: 1,
                senderId: '11223344',
                senderName: '测试成员',
                self,
                withdrawn: true,
                read: false,
                hasImage: true,
                hasForward: true,
                text: 'withdrawn-private-original',
            };
            const html = renderToStaticMarkup(
                React.createElement(ArchiveMessage, {
                    item,
                    busy: false,
                    onExpand: () => {},
                    onCollect: () => {},
                }),
            );
            assert.ok(html.includes('已撤回') && html.includes('withdrawn-private-original'));
            assert.ok(
                !html.includes('原内容已移除') &&
                    !html.includes('未读') &&
                    !html.includes('收藏首张图片') &&
                    !html.includes('展开转发'),
            );
            assert.ok(html.includes(self ? '我' : '测试成员'));
        }
        const { SessionDetail, toolOutcome } = await server.ssrLoadModule(
            '/src/agent/session-detail.tsx',
        );
        const { TokenLimit } = await server.ssrLoadModule('/src/settings/token-limit.tsx');
        for (const protocol of ['chat', 'responses', 'anthropic']) {
            const html = renderToStaticMarkup(
                React.createElement(TokenLimit, {
                    api: { protocol, chatTokenLimitField: 'max_tokens', maxOutputTokens: 4321 },
                    onChange: () => {},
                }),
            );
            assert.ok(html.includes('输出 Token 上限') && html.includes('4321'));
            assert.equal(html.includes('Chat 上限参数'), protocol === 'chat');
        }
        const preview = { kind: 'tool', name: 'send_image', result: { preview: true, sent: 0 } };
        assert.equal(toolOutcome(preview), '已预览');
        const duplicate = {
            kind: 'tool',
            name: 'send_sticker',
            status: 'done',
            result: { sent: 0, deduped: 1, messageIds: [] },
        };
        assert.equal(toolOutcome(duplicate), '已跳过重复发送');
        assert.equal(toolOutcome({ kind: 'tool', name: 'send_message', result: {} }), '未确认发送');
        assert.equal(
            toolOutcome({ kind: 'tool', name: 'send_message', isError: true, result: { sent: 1 } }),
            '执行失败',
        );
        const session = {
            id: 'test',
            started: 1,
            ended: 2346,
            status: 'noreply',
            model: 'test-model',
            usage: { totalTokens: 12, calls: 1 },
            sent: [],
            reason: '本轮未发送',
            records: [{ kind: 'assistant', text: null }, preview],
        };
        const detail = renderToStaticMarkup(React.createElement(SessionDetail, { session }));
        assert.ok(detail.includes('没有已确认发送的回复') && detail.includes('尚未发送'));
        assert.ok(!detail.includes('>null<') && !detail.includes('QQ 已确认 · 消息编号'));
        const skipped = renderToStaticMarkup(
            React.createElement(SessionDetail, { session: { ...session, records: [duplicate] } }),
        );
        assert.ok(
            skipped.includes('此次调用没有新增发送') && skipped.includes('没有已确认发送的回复'),
        );
        assert.ok(!skipped.includes('QQ 已确认 · 消息编号'));
        session.status = 'error';
        session.sent = [{ text: '失败前已发出的回复', messageId: '-123', ts: 1 }];
        const failed = renderToStaticMarkup(React.createElement(SessionDetail, { session }));
        assert.ok(
            failed.includes('已发送，后续处理异常') &&
                failed.includes('失败前已发出的回复') &&
                failed.includes('QQ 已确认') &&
                failed.includes('-123') &&
                !failed.includes('title="'),
        );
    } finally {
        await server.close();
    }
});
