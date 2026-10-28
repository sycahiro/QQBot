import { useEffect, useRef, useState } from 'react';
import { motion, useReducedMotion } from 'motion/react';
import { QrCode, RefreshCw } from 'lucide-react';
import { uiTransition } from './motion';
import { Notice } from './components/notice';
import { StatusSwap } from './components/status-swap';
import type { QqProcess, QqConnectionInfo, QqDiscoveryResult } from './desktop';

export function QqAccounts({
    ready,
    connection,
    onConnectionChange,
    cached,
    onDiscovery,
    serviceStage,
    onServiceStage,
}: {
    ready: boolean;
    connection: QqConnectionInfo | null;
    onConnectionChange: (status: QqConnectionInfo) => void;
    cached?: Extract<QqDiscoveryResult, { ok: true }> | null;
    onDiscovery?: (result: Extract<QqDiscoveryResult, { ok: true }>) => void;
    /** SnowLuma 状态由外层持有，切页回来才不会被重置成「未启动」。 */
    serviceStage: string | null;
    onServiceStage: (stage: string) => void;
}) {
    const [processes, setProcesses] = useState<QqProcess[] | null>(
        () =>
            cached?.processes ??
            (connection?.connected && connection.account
                ? [
                      {
                          pid: connection.account.pid,
                          processKey: null,
                          version: connection.account.version,
                          account: {
                              uin: connection.account.uin,
                              nickname: connection.account.nickname,
                          },
                          identityReady: false,
                          accountAmbiguous: false,
                      },
                  ]
                : null),
    );
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState('');
    const [revision, refresh] = useState(0);
    const [saving, setSaving] = useState(false);
    const [notice, setNotice] = useState('');
    const [serviceBusy, setServiceBusy] = useState(false);
    const reduced = useReducedMotion();
    const savingNow = useRef(false);
    const mounted = useRef(true);
    const scannedRevision = useRef<number | null>(null);
    const discoveryChanged = useRef(onDiscovery);
    discoveryChanged.current = onDiscovery;
    const startService = async () => {
        if (serviceBusy || !ready) return;
        setServiceBusy(true);
        setError('');
        try {
            const result = await window.pywebview!.api.start_snowluma();
            if (!mounted.current) return;
            if (result.ok) {
                onServiceStage(result.stage);
                setNotice('SnowLuma 已启动，正在检测本机 QQ…');
                refresh((value) => value + 1);
            } else {
                if (result.stage) onServiceStage(result.stage);
                setError(result.error.message);
            }
        } catch {
            if (mounted.current) setError('启动 SnowLuma 未确认，请重试');
        } finally {
            if (mounted.current) setServiceBusy(false);
        }
    };
    const stopService = async () => {
        if (serviceBusy || !ready) return;
        setServiceBusy(true);
        setError('');
        try {
            const result = await window.pywebview!.api.stop_snowluma();
            if (!mounted.current) return;
            if (result.ok) {
                onServiceStage(result.stage);
                setNotice('SnowLuma 已停止，下次检测前需要重新启动');
                refresh((value) => value + 1);
            } else {
                if (result.stage) onServiceStage(result.stage);
                setError(result.error.message);
            }
        } catch {
            if (mounted.current) setError('停止 SnowLuma 未确认，请重试');
        } finally {
            if (mounted.current) setServiceBusy(false);
        }
    };
    const locked = Boolean(
        connection?.connected ||
        connection?.state === 'connecting' ||
        connection?.state === 'disconnecting',
    );
    const connectionBusy =
        connection?.state === 'connecting' || connection?.state === 'disconnecting';
    const statusLabel = connection
        ? {
              idle: '尚未连接',
              connecting: '正在确认登录身份',
              ready: '已连接',
              disconnecting: '正在断开',
              disconnected: '连接已断开',
              error: '连接异常',
              closed: '已关闭',
          }[connection.state]
        : '尚未连接';
    useEffect(() => {
        mounted.current = true;
        return () => {
            mounted.current = false;
        };
    }, []);
    useEffect(() => {
        // SnowLuma 没起来时检测接口只会报「服务未启动」，交给常驻状态条提示即可。
        if (
            !ready ||
            !connection ||
            serviceStage !== 'running' ||
            (revision === 0 && connection.connected) ||
            scannedRevision.current === revision
        ) {
            setLoading(false);
            return;
        }
        scannedRevision.current = revision;
        let active = true;
        setLoading(true);
        setError('');
        void window
            .pywebview!.api.get_qq_processes()
            .then((result) => {
                if (!active) return;
                if (result.ok) {
                    setProcesses(result.processes);
                    if (result.warning) setNotice(result.warning);
                    discoveryChanged.current?.(result);
                } else setError(result.error.message);
            })
            .catch(() => {
                if (active) setError('无法读取 QQ 信息，请稍后刷新');
            })
            .finally(() => {
                if (active) setLoading(false);
            });
        return () => {
            active = false;
        };
    }, [ready, revision, connection?.connected, serviceStage]);

    const changeConnection = async (item: QqProcess | null) => {
        if (savingNow.current || loading || !ready || connectionBusy) return;
        if (item && (!item.account || !item.processKey || !item.identityReady)) return;
        savingNow.current = true;
        setSaving(true);
        setError('');
        setNotice(item ? '正在连接 QQ 并核对登录身份…' : '正在断开 QQ 连接…');
        try {
            const result = item
                ? await window.pywebview!.api.connect_qq_account({
                      pid: item.pid,
                      processKey: item.processKey!,
                      uin: item.account!.uin,
                  })
                : await window.pywebview!.api.disconnect_qq_account();
            if (!mounted.current) return;
            if (result.ok) {
                onConnectionChange(result.connection);
                setNotice(
                    result.connection.connected
                        ? 'QQ 已连接，当前仅接收消息；自动回复尚未启用。'
                        : 'QQ 连接已断开，客户端仍保持运行。',
                );
            } else {
                setError(result.error.message);
                setNotice('');
            }
        } catch {
            if (mounted.current) {
                setError('操作结果未确认，请检查连接状态；不要重复点击发送类操作');
                setNotice('');
            }
        } finally {
            savingNow.current = false;
            if (mounted.current) setSaving(false);
        }
    };

    return (
        <div className="desktop-sections">
            <section className="ui-card console-panel" aria-busy={serviceBusy}>
                <div className="console-panel-heading">
                    <div>
                        <h2>SnowLuma 引擎</h2>
                        <p>负责检测与接管本机 QQ 客户端，启动后常驻运行。</p>
                    </div>
                    <span
                        className={
                            'qq-account-status' +
                            (serviceStage === 'running' ? ' is-connected' : '') +
                            (serviceStage === 'error' ? ' is-error' : '')
                        }
                    >
                        {serviceStage === 'running'
                            ? '已启动'
                            : serviceStage === 'starting'
                              ? '启动中'
                              : serviceStage === 'error'
                                ? '启动失败'
                                : '未启动'}
                    </span>
                </div>
                <div className="qq-toolbar">
                    <span role="status">
                        {!ready
                            ? '等待桌面窗口就绪'
                            : serviceStage === 'running'
                              ? 'SnowLuma 已常驻运行；停止时会先断开 QQ 连接'
                              : serviceStage === 'starting'
                                ? 'SnowLuma 启动中…'
                                : serviceStage === 'error'
                                  ? 'SnowLuma 启动失败，可重试'
                                  : 'SnowLuma 未启动：检测与接管 QQ 进程需要它'}
                    </span>
                    {serviceStage === 'running' ? (
                        <button
                            className="qq-refresh"
                            disabled={!ready || serviceBusy}
                            onClick={() => void stopService()}
                        >
                            停止引擎
                        </button>
                    ) : (
                        <button
                            className="qq-refresh qq-connect"
                            disabled={!ready || serviceBusy || serviceStage === 'starting'}
                            onClick={() => void startService()}
                        >
                            {serviceStage === 'starting'
                                ? '启动中…'
                                : serviceStage === 'error'
                                  ? '重试启动'
                                  : '启动引擎'}
                        </button>
                    )}
                </div>
            </section>
            <section className="ui-card console-panel" aria-busy={loading}>
                <div className="console-panel-heading">
                    <div>
                        <h2>已打开的 QQ</h2>
                        <p>在下面列表里挑一个账号连接，连哪个由你决定。</p>
                    </div>
                    <QrCode size={18} />
                </div>
                <div className="qq-toolbar">
                    <span role="status">
                        {!ready
                            ? '等待桌面窗口就绪'
                            : loading
                              ? '正在检测本机 QQ…'
                              : error && !processes
                                ? '检测未完成'
                                : processes
                                  ? `发现 ${processes.length} 个 QQ 客户端`
                                  : '准备检测'}
                    </span>
                    <button
                        className="qq-refresh"
                        disabled={!ready || loading || saving || serviceStage !== 'running'}
                        onClick={() => {
                            setNotice('');
                            refresh((value) => value + 1);
                        }}
                    >
                        <RefreshCw size={15} className={loading ? 'qq-scanning' : ''} />
                        刷新检测
                    </button>
                </div>
                <div
                    className={
                        'qq-service-hint' +
                        (!ready || serviceStage === null
                            ? ''
                            : serviceStage === 'running'
                              ? ' is-ready'
                              : serviceStage === 'starting'
                                ? ' is-pending'
                                : ' is-error')
                    }
                >
                    <span className="status-dot" />
                    <StatusSwap
                        className="qq-service-text"
                        text={
                            !ready
                                ? '等待桌面窗口就绪后再启动 SnowLuma'
                                : serviceStage === null
                                  ? '正在读取 SnowLuma 状态…'
                                  : serviceStage === 'running'
                                    ? 'SnowLuma 服务启动成功，正在接管本机 QQ'
                                    : serviceStage === 'starting'
                                      ? 'SnowLuma 正在启动，稍后自动检测本机 QQ'
                                      : serviceStage === 'error'
                                        ? 'SnowLuma 启动失败，可在上方「SnowLuma 引擎」里重试'
                                        : 'SnowLuma 服务未启动，请先在上方「SnowLuma 引擎」里启动'
                        }
                    />
                </div>
                <div
                    className={
                        'qq-service-hint' +
                        (connection?.connected
                            ? ' is-ready'
                            : connectionBusy
                              ? ' is-pending'
                              : ' is-error')
                    }
                >
                    <span className="status-dot" />
                    <StatusSwap
                        className="qq-service-text"
                        text={
                            !ready
                                ? '等待桌面窗口就绪后再连接 QQ'
                                : connection?.connected
                                  ? `QQ 已连接 · ${connection.account?.nickname || '机器人账号'}（${connection.account?.uin ?? ''}）`
                                  : connection?.state === 'connecting'
                                    ? '正在连接 QQ 并核对登录身份…'
                                    : connection?.state === 'disconnecting'
                                      ? '正在断开 QQ 连接…'
                                      : connection?.error
                                        ? `QQ 连接异常 · ${connection.error}`
                                        : 'QQ 未连接 · 在下面列表里点「连接」'
                        }
                    />
                    {locked && (
                        <button
                            className="qq-refresh"
                            disabled={loading || saving || connectionBusy}
                            onClick={() => void changeConnection(null)}
                        >
                            断开连接
                        </button>
                    )}
                </div>
                {error && (
                    <div className="desktop-error" role="alert">
                        {error}
                    </div>
                )}
                <Notice title="QQ Agent" message={notice} onClose={() => setNotice('')} />
                {processes?.length === 0 && (
                    <motion.div
                        className="desktop-empty"
                        initial={reduced ? false : { opacity: 0, y: 6 }}
                        animate={{ opacity: 1, y: 0 }}
                        transition={uiTransition(reduced)}
                    >
                        <span className="empty-icon">
                            <QrCode size={28} />
                        </span>
                        <h3>未发现正在运行的 QQ</h3>
                        <p>先打开 Windows QQ 并登录账号，再点击刷新检测。</p>
                    </motion.div>
                )}
                {Boolean(processes?.length) && (
                    <div className="qq-process-list">
                        {processes!.map((item, index) => {
                            const current =
                                connection?.account?.pid === item.pid &&
                                connection.account.uin === item.account?.uin;
                            const connected = Boolean(current && connection?.connected);
                            const busyHere = current && connectionBusy;
                            return (
                                <motion.article
                                    className={'qq-process-row' + (connected ? ' is-selected' : '')}
                                    key={item.pid}
                                    initial={reduced ? false : { opacity: 0, x: 32 }}
                                    animate={{ opacity: 1, x: 0 }}
                                    transition={{
                                        ...uiTransition(reduced),
                                        delay: reduced ? 0 : Math.min(index, 8) * 0.06,
                                    }}
                                >
                                    <span className="qq-account-icon">
                                        <QrCode size={21} />
                                    </span>
                                    <div className="qq-account-name">
                                        <strong>
                                            {item.account?.nickname ||
                                                (item.account ? 'QQ 账号' : '账号尚未识别')}
                                        </strong>
                                        <small>
                                            {item.account
                                                ? `QQ 号：${item.account.uin}`
                                                : item.accountAmbiguous
                                                  ? '账号信息有歧义，需要进一步确认'
                                                  : '未读取到本地账号信息'}
                                        </small>
                                    </div>
                                    <div className="qq-process-info">
                                        <span>进程 {item.pid}</span>
                                        <small>
                                            {item.version
                                                ? `QQ ${item.version}`
                                                : '客户端版本暂不可用'}
                                        </small>
                                    </div>
                                    <div className="qq-account-action">
                                        <span
                                            className={
                                                'qq-account-status' +
                                                (connected ? ' is-connected' : '')
                                            }
                                        >
                                            {connected
                                                ? '已连接'
                                                : busyHere
                                                  ? connection?.state === 'connecting'
                                                      ? '连接中'
                                                      : '断开中'
                                                  : '未接入'}
                                        </span>
                                        <div className="qq-account-button">
                                            {!connected && (
                                                <button
                                                    className="qq-refresh qq-connect"
                                                    disabled={
                                                        loading ||
                                                        saving ||
                                                        connectionBusy ||
                                                        Boolean(connection?.connected) ||
                                                        !item.identityReady
                                                    }
                                                    onClick={() => void changeConnection(item)}
                                                >
                                                    {busyHere ? statusLabel : '连接'}
                                                </button>
                                            )}
                                        </div>
                                    </div>
                                </motion.article>
                            );
                        })}
                    </div>
                )}
                {Boolean(processes?.length) && (
                    <p className="qq-discovery-note">
                        连接后，到 QQ Agent 页开启自动回复并查看会话。
                    </p>
                )}
            </section>
        </div>
    );
}
