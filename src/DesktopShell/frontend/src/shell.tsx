import { useEffect, useState } from 'react';
import {
    Bot,
    Cable,
    Clock3,
    LayoutDashboard,
    MessageSquare,
    Monitor,
    Moon,
    QrCode,
    SlidersHorizontal,
    Sun,
    Terminal,
} from 'lucide-react';
import {
    useDesktop,
    useQqConnection,
    useAgentStatus,
    type DesktopInfo,
    type QqConnectionInfo,
    type QqDiscoveryResult,
} from './desktop';
import { chatLabel, type AgentStatus } from './business';
import { useSessions, statusNames } from './agent/sessions';
import { useTheme } from './theme';
import { Resources } from './resources';
import { QqAccounts } from './qq';
import { AgentWorkspace } from './agent';
import { resetSettingsEditor } from './agent/use-settings';
import { Logs } from './diagnostics';
import { SystemSettings } from './settings';
import { CloseDialog } from './components/close-dialog';
import { useNavHighlight } from './components/nav-highlight';
import { Notice } from './components/notice';
import { StatusSwap } from './components/status-swap';

const pages = [
    {
        id: 'overview',
        group: '工作空间',
        title: '总览',
        icon: LayoutDashboard,
        caption: '连接、会话与运行状态',
    },
    {
        id: 'connect',
        group: '工作空间',
        title: '连接',
        icon: Cable,
        caption: '选择并连接本机的个人 QQ',
    },
    {
        id: 'logs',
        group: '工作空间',
        title: '运行日志',
        icon: Terminal,
        caption: '查看运行记录与处理过程',
    },
    {
        id: 'agent',
        group: '机器人',
        title: 'QQ Agent',
        icon: Bot,
        caption: '个人 QQ 的会话、记忆与自动回复',
    },
    {
        id: 'settings',
        group: '管理',
        title: '系统设置',
        icon: SlidersHorizontal,
        caption: '外观、全局服务与应用信息',
    },
] as const;
type Page = (typeof pages)[number]['id'];

const groups = ['工作空间', '机器人', '管理'] as const;

export function DesktopShell() {
    const { info, error, retry } = useDesktop();
    const { connection, setConnection } = useQqConnection(Boolean(info));
    const { status, setStatus } = useAgentStatus(Boolean(info));
    const { theme, setTheme } = useTheme();
    const [page, setPage] = useState<Page>('overview');
    const [qqDiscovery, setQqDiscovery] = useState<Extract<QqDiscoveryResult, { ok: true }> | null>(
        null,
    );
    const [snowStage, setSnowStage] = useState<string | null>(null);
    const current = pages.find((item) => item.id === page)!;
    const connected = Boolean(connection?.connected && connection.account?.uin);
    const agentCurrent = connected && status?.account === connection?.account?.uin;
    const replying = Boolean(agentCurrent && status?.enabled);
    const modelLabel = status?.model ? `模型 · ${status.model}` : '模型 · 未配置';
    const snowLabel =
        snowStage === null
            ? 'SnowLuma · 检测中'
            : snowStage === 'running'
              ? 'SnowLuma · 已启动'
              : snowStage === 'starting'
                ? 'SnowLuma · 启动中'
                : snowStage === 'error'
                  ? 'SnowLuma · 异常'
                  : 'SnowLuma · 未启动';
    const qqLabel = error
        ? 'QQ · 连接异常'
        : connected
          ? 'QQ · 已连接'
          : connection?.state === 'connecting'
            ? 'QQ · 连接中'
            : 'QQ · 未连接';
    const replyLabel = replying
        ? status?.running
            ? '自动回复 · 处理中'
            : '自动回复 · 开启'
        : agentCurrent && status?.manual
          ? '自动回复 · 手动'
          : '自动回复 · 关闭';
    useEffect(() => {
        let active = true;
        const poll = () => {
            // pywebview 桥在窗口就绪前还不存在，同步访问会把整棵 React 树炸掉。
            const api = (window as { pywebview?: { api?: unknown } }).pywebview?.api as
                | { get_snowluma_status?: () => Promise<{ stage: string; error: string | null }> }
                | undefined;
            if (!api?.get_snowluma_status) return;
            api.get_snowluma_status()
                .then((status) => {
                    if (active) setSnowStage(status.stage);
                })
                .catch(() => undefined);
        };
        poll();
        const timer = setInterval(poll, 5000);
        return () => {
            active = false;
            clearInterval(timer);
        };
    }, []);
    useEffect(() => {
        resetSettingsEditor();
    }, [connection?.connected, connection?.account?.uin, connection?.account?.pid]);
    const { navRef, highlightRef } = useNavHighlight(page);
    return (
        <div className="console-shell" data-desktop-ready={Boolean(info)}>
            <CloseDialog />
            <Notice
                title="自动回复已暂停"
                message={agentCurrent ? status?.notice || '' : ''}
                onClose={() => {}}
            />
            <aside className="console-sidebar-frame console-sidebar desktop-sidebar">
                <button
                    className="console-brand"
                    onClick={() => setPage('overview')}
                    aria-label="QQBot 总览"
                >
                    <span className="console-brand-icon">
                        <Bot size={24} strokeWidth={1.7} />
                    </span>
                    <span>
                        <strong>QQBot</strong>
                        <small>你的 AI 聊天工作台</small>
                    </span>
                </button>
                <nav aria-label="主导航" ref={navRef}>
                    <span className="console-nav-highlight" ref={highlightRef} aria-hidden="true" />
                    {groups.map((group) => (
                        <div className="nav-group" key={group}>
                            <p>{group}</p>
                            {pages
                                .filter((item) => item.group === group)
                                .map(({ id, title, icon: Icon }) => (
                                    <button
                                        key={id}
                                        onClick={() => setPage(id)}
                                        aria-current={page === id ? 'page' : undefined}
                                        className={
                                            'console-nav-item' + (page === id ? ' is-active' : '')
                                        }
                                    >
                                        <Icon size={18} />
                                        <span>{title}</span>
                                    </button>
                                ))}
                        </div>
                    ))}
                </nav>
                <div className="desktop-location">
                    <span className="status-dot" />
                    本地工作空间
                    <small>Windows · 独立窗口</small>
                </div>
            </aside>
            <div className="console-main-column">
                <header className="console-topbar">
                    <span className="breadcrumb">
                        {current.group} <span>/</span> <strong>{current.title}</strong>
                    </span>
                    <div className="topbar-actions">
                        <div className="workspace-status" aria-label="当前运行状态">
                            <span className="workspace-badge workspace-model">
                                <span
                                    className={'status-dot' + (status?.model ? '' : ' is-muted')}
                                />
                                <StatusSwap className="workspace-model-name" text={modelLabel} />
                            </span>
                            <span
                                className={
                                    'workspace-badge workspace-snowluma' +
                                    (snowStage === 'running' ? ' is-connected' : '') +
                                    (snowStage === 'error' ? ' is-error' : '')
                                }
                                aria-label="SnowLuma 服务状态"
                            >
                                <span
                                    className={
                                        'status-dot' +
                                        (snowStage === 'running' || snowStage === 'error'
                                            ? ''
                                            : ' is-muted')
                                    }
                                />
                                <StatusSwap text={snowLabel} />
                            </span>
                            <span
                                className={
                                    'workspace-badge workspace-account' +
                                    (connected ? ' is-connected' : '') +
                                    (error ? ' is-error' : '')
                                }
                                aria-label="个人 QQ 连接状态"
                            >
                                <span className={'status-dot' + (!connected ? ' is-muted' : '')} />
                                <StatusSwap text={qqLabel} />
                            </span>
                            <span
                                className={
                                    'workspace-badge workspace-reply' + (replying ? ' is-on' : '')
                                }
                                aria-label="自动回复状态"
                            >
                                <span className={'status-dot' + (replying ? '' : ' is-muted')} />
                                <StatusSwap text={replyLabel} />
                            </span>
                        </div>
                        <button
                            className="btn btn-icon"
                            aria-label="切换明暗主题"

                            onClick={() =>
                                setTheme(
                                    document.documentElement.classList.contains('dark')
                                        ? 'light'
                                        : 'dark',
                                )
                            }
                        >
                            <Sun size={17} className="sun-icon" />
                            <Moon size={17} className="moon-icon" />
                        </button>
                    </div>
                </header>
                <main className="console-scroll" id="main-content">
                    <div className="console-content">
                        {error && (
                            <div role="alert" className="desktop-error">
                                {error}
                                {!info && (
                                    <button className="btn" onClick={retry}>
                                        重新连接窗口
                                    </button>
                                )}
                            </div>
                        )}
                        <div className="page-enter" key={page}>
                            <div className="console-page-heading">
                                <div>
                                    <p className="console-eyebrow">
                                        {page === 'overview' ? 'YOUR WORKSPACE' : 'QQBOT DESKTOP'}
                                    </p>
                                    <h1>{page === 'overview' ? '工作台' : current.title}</h1>
                                    <p>{current.caption}</p>
                                </div>
                            </div>
                            {page === 'overview' ? (
                                <Overview
                                    key={
                                        connection?.connected
                                            ? `${connection.account?.uin}:${connection.account?.pid}`
                                            : 'offline'
                                    }
                                    info={info}
                                    connection={connection}
                                    agent={status}
                                />
                            ) : page === 'settings' ? (
                                <SystemSettings info={info} theme={theme} setTheme={setTheme} />
                            ) : page === 'connect' ? (
                                <QqAccounts
                                    ready={Boolean(info)}
                                    connection={connection}
                                    onConnectionChange={setConnection}
                                    cached={qqDiscovery}
                                    onDiscovery={setQqDiscovery}
                                    serviceStage={snowStage}
                                    onServiceStage={setSnowStage}
                                />
                            ) : page === 'agent' ? (
                                <AgentWorkspace
                                    ready={Boolean(info)}
                                    status={status}
                                    connection={connection}
                                    onStatus={setStatus}
                                    onConnect={() => setPage('connect')}
                                />
                            ) : page === 'logs' ? (
                                <Logs ready={Boolean(info)} />
                            ) : null}
                        </div>
                    </div>
                </main>
            </div>
        </div>
    );
}

function Overview({
    info,
    connection,
    agent,
}: {
    info: DesktopInfo | null;
    connection: QqConnectionInfo | null;
    agent: AgentStatus | null;
}) {
    const [elapsed, setElapsed] = useState(0);
    const connected = Boolean(connection?.connected && connection.account?.uin);
    const { items } = useSessions(Boolean(info) && connected);
    const recent = connected ? items : [];
    useEffect(() => {
        const start = performance.now();
        const update = () =>
            setElapsed((info?.uptimeSeconds ?? 0) + Math.floor((performance.now() - start) / 1000));
        update();
        const timer = setInterval(update, 1000);
        return () => clearInterval(timer);
    }, [info]);
    const metrics = [
        {
            label: '桌面窗口',
            value: info ? '已就绪' : '载入中',
            hint: '直接在应用中使用工作台',
            icon: Monitor,
        },
        {
            label: 'QQ 账号',
            value: connection?.connected
                ? '已连接'
                : connection?.state === 'connecting'
                  ? '连接中'
                  : '尚未连接',
            hint: connection?.connected ? '账号详情见「连接」页' : '在「连接」页选择并连接账号',
            icon: QrCode,
        },
        {
            label: 'QQ Agent',
            value: agent?.enabled
                ? agent.running
                    ? '正在处理'
                    : '正在待命'
                : agent?.manual
                  ? '手动处理中'
                  : '仅接收消息',
            hint: agent?.enabled
                ? '只处理白名单中的新消息'
                : agent?.manual
                  ? '仅执行本次手动请求'
                  : '自动回复关闭，可手动处理一次',
            icon: Bot,
        },
        {
            label: '运行时长',
            value: elapsed < 60 ? `${elapsed} 秒` : `${Math.floor(elapsed / 60)} 分`,
            hint: '本次桌面应用的运行时间',
            icon: Clock3,
        },
    ];
    return (
        <div className="desktop-sections">
            <div className="console-metrics-grid">
                {metrics.map(({ label, value, hint, icon: Icon }) => (
                    <section className="ui-card console-metric" key={label}>
                        <div className="metric-label">
                            {label}
                            <Icon size={18} />
                        </div>
                        <strong className="metric-value">{value}</strong>
                        <p>{hint}</p>
                    </section>
                ))}
            </div>
            <Resources ready={Boolean(info)} />
            <section className="ui-card console-panel">
                <div className="console-panel-heading">
                    <div>
                        <h2>最近会话</h2>
                        <p>模型的每次处理，都有记录可查</p>
                    </div>
                    <MessageSquare size={18} />
                </div>
                {recent.length ? (
                    <div className="recent-sessions">
                        {recent.slice(0, 5).map((item) => (
                            <article key={item.id}>
                                <div>
                                    <strong>{chatLabel(item).title}</strong>
                                    <small>{chatLabel(item).number}</small>
                                    <p>{item.triggerText}</p>
                                </div>
                                <span className={'session-status ' + item.status}>
                                    {statusNames[item.status]}
                                </span>
                            </article>
                        ))}
                    </div>
                ) : (
                    <div className="desktop-empty">
                        <span className="empty-icon">
                            <MessageSquare size={25} strokeWidth={1.5} />
                        </span>
                        <h3>还没有模型会话</h3>
                        <p>开启自动回复后，新的处理记录会显示在这里。</p>
                    </div>
                )}
            </section>
        </div>
    );
}
