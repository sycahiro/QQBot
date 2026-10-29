import type { ReactNode } from 'react';
import type { QqConnectionInfo } from '../desktop';

/** 未连接时只显示提示，连接后才渲染功能内容；账号变化时立刻卸载旧内容。 */
function ConnectionGate({
    connected,
    connecting,
    identity,
    icon,
    title,
    pendingTitle,
    description,
    pendingText,
    action,
    children,
}: {
    connected: boolean;
    connecting: boolean;
    identity: string;
    icon: ReactNode;
    title: string;
    pendingTitle: string;
    description: string;
    pendingText: string;
    action?: ReactNode;
    children: () => ReactNode;
}) {
    return (
        <div className="page-enter" key={identity || (connecting ? 'connecting' : 'offline')}>
            {connected ? (
                children()
            ) : (
                <section className="ui-card console-panel desktop-empty" aria-busy={connecting}>
                    <span className={`empty-icon${connecting ? ' connection-pending' : ''}`}>
                        {icon}
                    </span>
                    <h3>{connecting ? pendingTitle : title}</h3>
                    <p>{connecting ? pendingText : description}</p>
                    {action ? <div className="empty-action">{action}</div> : null}
                </section>
            )}
        </div>
    );
}

export function ConnectionBoundary({
    ready,
    connection,
    icon,
    description,
    onConnect,
    children,
}: {
    ready: boolean;
    connection?: QqConnectionInfo | null;
    icon: ReactNode;
    description: string;
    onConnect?: () => void;
    children: (account: NonNullable<QqConnectionInfo['account']>) => ReactNode;
}) {
    const connected = Boolean(
        ready && connection?.connected && connection.state === 'ready' && connection.account,
    );
    const connecting = connection?.state === 'connecting';
    const identity = connected ? `${connection!.account!.uin}:${connection!.account!.pid}` : '';
    return (
        <ConnectionGate
            connected={connected}
            connecting={Boolean(connecting)}
            identity={identity}
            icon={icon}
            title="请先在「连接」页连接个人 QQ"
            pendingTitle="正在连接个人 QQ"
            description={description}
            pendingText="正在连接并核验机器人账号，请稍候…"
            action={
                onConnect ? (
                    <button className="btn btn-accent" type="button" onClick={onConnect}>
                        前往连接页
                    </button>
                ) : undefined
            }
        >
            {() => children(connection!.account!)}
        </ConnectionGate>
    );
}
