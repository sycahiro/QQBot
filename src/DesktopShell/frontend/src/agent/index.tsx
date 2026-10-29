import { useState } from 'react';
import {
    MessageSquare,
    SlidersHorizontal,
    Wallet,
    Bot,
    Brain,
    Sparkles,
    Smile,
} from 'lucide-react';
import type { AgentStatus } from '../business';
import type { QqConnectionInfo } from '../desktop';
import { Archive } from './archive';
import { BotSettings } from './settings';
import { Sessions } from './sessions';
import { Usage } from './usage';
import { Memory } from './memory';
import { Extensions } from './extensions';
import { Stickers } from './stickers';
import { ConnectionBoundary } from '../components/connection-boundary';
import { useTabNavigation } from '../components/tab-navigation';
import { useNavHighlight } from '../components/nav-highlight';
import { Notice } from '../components/notice';

const tabs = [
    { id: 'sessions', label: '会话', icon: Bot },
    { id: 'archive', label: '聊天存档', icon: MessageSquare },
    { id: 'memory', label: '记忆', icon: Brain },
    { id: 'stickers', label: '表情库', icon: Smile },
    { id: 'usage', label: '用量', icon: Wallet },
    { id: 'settings', label: '机器人设置', icon: SlidersHorizontal },
    { id: 'extensions', label: '扩展', icon: Sparkles },
] as const;

export function AgentWorkspace({
    ready,
    status,
    connection,
    onStatus,
    onConnect,
}: {
    ready: boolean;
    status: AgentStatus | null;
    connection: QqConnectionInfo | null;
    onStatus: (status: AgentStatus) => void;
    onConnect: () => void;
}) {
    const [error, setError] = useState('');
    return (
        <div className="desktop-sections">
            <ConnectionBoundary
                ready={ready}
                connection={connection}
                icon={<Bot size={28} />}
                description="连接个人 QQ 后，会话、记忆与设置会显示在这里。"
                onConnect={onConnect}
            >
                {() => (
                    <ConnectedWorkspace
                        ready={ready}
                        status={status}
                        connection={connection!}
                        onStatus={onStatus}
                        onError={setError}
                    />
                )}
            </ConnectionBoundary>
            <Notice title="自动回复" message={error} error onClose={() => setError('')} />
        </div>
    );
}

function ConnectedWorkspace({
    ready,
    status,
    connection,
    onStatus,
    onError,
}: {
    ready: boolean;
    status: AgentStatus | null;
    connection: QqConnectionInfo;
    onStatus: (status: AgentStatus) => void;
    onError: (message: string) => void;
}) {
    const { tab, setTab, panel } = useTabNavigation<(typeof tabs)[number]['id']>('sessions');
    const { navRef, highlightRef } = useNavHighlight(tab);
    const [busy, setBusy] = useState(false);
    const change = async () => {
        const account = connection?.account?.uin || status?.account;
        if (!account || !status || busy) return;
        setBusy(true);
        onError('');
        try {
            const result = await window.pywebview!.api.set_auto_reply(!status.enabled, account);
            if (result.ok) onStatus(result.status);
            else onError(result.error.message);
        } catch {
            onError('开关状态未确认，请稍候检查状态');
        } finally {
            setBusy(false);
        }
    };
    return (
        <div className="desktop-sections">
            <div className="ui-card agent-control">
                <div>
                    <strong>
                        {status?.enabled
                            ? status.running
                                ? '正在处理'
                                : '正在待命'
                            : status?.manual
                              ? '正在手动处理'
                              : status?.active
                                ? '正在停止处理'
                                : '仅接收消息'}
                    </strong>
                    <p>
                        {status?.enabled
                            ? '只处理白名单内的新消息'
                            : status?.manual
                              ? '仅执行本次手动请求，自动回复保持关闭'
                              : '已关闭自动回复，可从聊天存档手动处理消息'}
                    </p>
                </div>
                <button
                    className="reply-switch"
                    role="switch"
                    aria-label="自动回复"
                    aria-checked={Boolean(status?.enabled)}
                    disabled={
                        !ready ||
                        !status ||
                        busy ||
                        (!status.enabled && (!connection?.connected || status.active > 0))
                    }
                    onClick={() => void change()}
                >
                    <span />
                    自动回复
                </button>
            </div>
            <nav className="agent-tabs agent-workspace-tabs" aria-label="机器人功能" ref={navRef}>
                <span className="agent-tab-highlight" ref={highlightRef} aria-hidden="true" />
                {tabs.map(({ id, label, icon: Icon }) => (
                    <button
                        key={id}
                        aria-current={tab === id ? 'page' : undefined}
                        onClick={() => setTab(id)}
                    >
                        <Icon size={17} />
                        <span>{label}</span>
                    </button>
                ))}
            </nav>
            <div ref={panel} className="tab-panel-frame">
                <div className="desktop-sections agent-tab-panel page-enter" key={tab}>
                    {tab === 'sessions' ? (
                        <Sessions ready={ready} />
                    ) : tab === 'archive' ? (
                        <Archive ready={ready} />
                    ) : tab === 'memory' ? (
                        <Memory ready={ready} />
                    ) : tab === 'stickers' ? (
                        <Stickers ready={ready} account={connection.account!.uin} />
                    ) : tab === 'usage' ? (
                        <Usage ready={ready} />
                    ) : tab === 'extensions' ? (
                        <Extensions ready={ready} />
                    ) : (
                        <BotSettings ready={ready} account={connection.account!.uin} />
                    )}
                </div>
            </div>
        </div>
    );
}
