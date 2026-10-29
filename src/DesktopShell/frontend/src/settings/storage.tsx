import { useEffect, useRef, useState } from 'react';
import { Database, FileClock, HardDrive, RefreshCw, Save, Trash2 } from 'lucide-react';
import { useConfirm } from '../components/confirmation';
import { AnimatedList } from '../components/animated-list';
import { Disclosure } from '../components/disclosure';
import { Notice } from '../components/notice';
import {
    storageBytes as bytes,
    storageCategories as categories,
    type StorageOverview,
    type StoragePolicy,
    type StorageRequest,
} from './storage-types';

let cachedDraft: { maxMb: string; days: string; engineDays: string } | null = null;

function segments(data: StorageOverview) {
    return [
        { label: '日志', value: data.totals.logsBytes, tone: 'tone-a' },
        { label: '账号数据', value: data.totals.accountBytes, tone: 'tone-b' },
        { label: '临时文件', value: data.totals.temporaryBytes, tone: 'tone-c' },
        { label: 'SnowLuma 服务数据', value: data.totals.serviceBytes, tone: 'tone-d' },
    ];
}

function StorageBar({ data }: { data: StorageOverview }) {
    const items = segments(data);
    const total = items.reduce((sum, item) => sum + item.value, 0);
    return (
        <div className="storage-bar" role="img" aria-label="存储占用占比">
            {total > 0 &&
                items.map(
                    (item) =>
                        item.value > 0 && (
                            <span
                                key={item.label}
                                className={item.tone}
                                style={{ flexGrow: item.value }}
                                title={`${item.label} ${bytes(item.value)}`}
                            />
                        ),
                )}
        </div>
    );
}

export function StorageSettings({ ready }: { ready: boolean }) {
    const confirm = useConfirm();
    const [data, setData] = useState<StorageOverview | null>(null);
    const [maxMb, setMaxMb] = useState(cachedDraft?.maxMb ?? ''),
        [days, setDays] = useState(cachedDraft?.days ?? ''),
        [engineDays, setEngineDays] = useState(cachedDraft?.engineDays ?? '');
    const [busy, setBusy] = useState(false),
        [notice, setNotice] = useState(''),
        [failed, setFailed] = useState(false);
    const mounted = useRef(false),
        working = useRef(false),
        dirty = useRef(Boolean(cachedDraft));
    const apply = (value: StorageOverview, reset = false) => {
        setData(value);
        if (reset || !dirty.current) {
            setMaxMb(String(value.settings.logMaxTotalMb));
            setDays(String(value.settings.logRetainDays));
            setEngineDays(String(value.settings.engineRetainDays));
            dirty.current = false;
            cachedDraft = null;
        }
    };
    const report = (message: string, error = false) => {
        setFailed(error);
        setNotice(message);
    };
    const load = async () => {
        if (working.current) return;
        working.current = true;
        setBusy(true);
        try {
            const result = await window.pywebview!.api.get_storage();
            if (!mounted.current) return;
            if (result.ok) apply(result);
            else report(result.error.message, true);
        } catch {
            if (mounted.current) report('存储信息暂时无法读取', true);
        } finally {
            working.current = false;
            if (mounted.current) setBusy(false);
        }
    };
    useEffect(() => {
        mounted.current = true;
        if (ready) void load();
        return () => {
            mounted.current = false;
        };
    }, [ready]);
    const save = async () => {
        if (working.current) return;
        const value: StoragePolicy = {
            logMaxTotalMb: Number(maxMb),
            logRetainDays: Number(days),
            engineRetainDays: Number(engineDays),
        };
        if (
            !maxMb.trim() ||
            !days.trim() ||
            !engineDays.trim() ||
            !Number.isInteger(value.logMaxTotalMb) ||
            value.logMaxTotalMb < 1 ||
            value.logMaxTotalMb > 65536 ||
            !Number.isInteger(value.logRetainDays) ||
            value.logRetainDays < 0 ||
            value.logRetainDays > 36500 ||
            !Number.isInteger(value.engineRetainDays) ||
            value.engineRetainDays < 0 ||
            value.engineRetainDays > 36500
        ) {
            report('请填写有效的日志容量和保留天数', true);
            return;
        }
        working.current = true;
        setBusy(true);
        try {
            const result = await window.pywebview!.api.save_storage_settings(value);
            if (!mounted.current) return;
            if (result.ok) {
                apply(result.overview, true);
                report(
                    result.cleanup.failures.length
                        ? '设置已保存，部分旧日志暂时无法清理'
                        : '已保存',
                    Boolean(result.cleanup.failures.length),
                );
            } else report(result.error.message, true);
        } catch {
            if (mounted.current) report('保存结果未确认，请刷新检查', true);
        } finally {
            working.current = false;
            if (mounted.current) setBusy(false);
        }
    };
    const cleanup = async (request: StorageRequest, title: string, message: string) => {
        if (working.current) return;
        working.current = true;
        setBusy(true);
        try {
            if (
                !(await confirm(message, { title, confirmLabel: '清理', danger: true })) ||
                !mounted.current
            )
                return;
            const result = await window.pywebview!.api.cleanup_storage(request);
            if (!mounted.current) return;
            if (result.ok) {
                apply(result.overview);
                const c = result.cleanup;
                report(
                    `已清理 ${c.deletedRows} 条记录、${c.deletedFiles} 个文件，释放 ${bytes(c.freedBytes)}${c.failures.length ? '；' + c.failures[0] : ''}`,
                    !result.success,
                );
            } else report(result.error.message, true);
        } catch {
            if (mounted.current) report('清理结果未确认，请刷新检查', true);
        } finally {
            working.current = false;
            if (mounted.current) setBusy(false);
        }
    };
    if (!ready)
        return (
            <section className="ui-card console-panel desktop-empty">
                <HardDrive size={28} />
                <h3>正在读取存储信息</h3>
            </section>
        );
    const changed = Boolean(
        data &&
        (maxMb !== String(data.settings.logMaxTotalMb) ||
            days !== String(data.settings.logRetainDays) ||
            engineDays !== String(data.settings.engineRetainDays)),
    );
    return (
        <div className="desktop-sections storage-settings">
            <Notice
                title={failed ? '操作未完成' : '存储管理'}
                message={notice}
                error={failed}
                onClose={() => setNotice('')}
            />
            <section className="ui-card console-panel">
                <div className="console-panel-heading">
                    <div>
                        <h2>存储概览</h2>
                        <p>查看日志、账号、临时文件和 SnowLuma 服务数据的已统计占用。</p>
                    </div>
                    <button className="btn" disabled={busy} onClick={() => void load()}>
                        <RefreshCw size={15} />
                        {busy ? '正在处理…' : '刷新'}
                    </button>
                </div>
                {data ? (
                    <div className="storage-overview">
                        <div className="storage-total">
                            <div className="storage-total-label">
                                <span className="storage-total-icon">
                                    <HardDrive size={18} />
                                </span>
                                <div>
                                    <strong>已统计总占用</strong>
                                    <small>日志、账号和服务数据及临时文件</small>
                                </div>
                            </div>
                            <strong className="storage-total-value">
                                {bytes(data.totals.managedBytes)}
                            </strong>
                        </div>
                        <StorageBar data={data} />
                        <div className="storage-metrics">
                            {segments(data).map((segment) => (
                                <div className="storage-metric" key={segment.label}>
                                    <small>
                                        <i className={'storage-dot ' + segment.tone} />
                                        {segment.label}
                                    </small>
                                    <strong>{bytes(segment.value)}</strong>
                                </div>
                            ))}
                        </div>
                        <p className="storage-overview-note">
                            SnowLuma 服务数据不含已计入账号数据的索引。
                        </p>
                    </div>
                ) : (
                    <p className="action-notice">{busy ? '正在统计…' : '点击刷新读取存储信息。'}</p>
                )}
            </section>
            {data && (
                <>
                    <section className="ui-card console-panel">
                        <div className="console-panel-heading">
                            <div>
                                <h2>日志保留</h2>
                                <p>按启动时间和日期保留日志；本次运行和当天引擎日志始终保留。</p>
                            </div>
                            <FileClock size={18} />
                        </div>
                        <fieldset disabled={busy} className="bot-form-grid bot-fieldset">
                            <label>
                                日志总量上限（MB）
                                <input
                                    type="number"
                                    min={1}
                                    max={65536}
                                    step={1}
                                    value={maxMb}
                                    onChange={(e) => {
                                        dirty.current = true;
                                        cachedDraft = {
                                            ...(cachedDraft ?? { maxMb, days, engineDays }),
                                            maxMb: e.target.value,
                                        };
                                        setMaxMb(e.target.value);
                                    }}
                                />
                            </label>
                            <label>
                                应用日志保留天数
                                <input
                                    type="number"
                                    min={0}
                                    max={36500}
                                    step={1}
                                    value={days}
                                    onChange={(e) => {
                                        dirty.current = true;
                                        cachedDraft = {
                                            ...(cachedDraft ?? { maxMb, days, engineDays }),
                                            days: e.target.value,
                                        };
                                        setDays(e.target.value);
                                    }}
                                />
                                <small>设为 0 时仅按容量清理旧日志。</small>
                            </label>
                            <label>
                                引擎日志保留天数
                                <input
                                    type="number"
                                    min={0}
                                    max={36500}
                                    step={1}
                                    value={engineDays}
                                    onChange={(e) => {
                                        dirty.current = true;
                                        cachedDraft = {
                                            ...(cachedDraft ?? { maxMb, days, engineDays }),
                                            engineDays: e.target.value,
                                        };
                                        setEngineDays(e.target.value);
                                    }}
                                />
                                <small>设为 0 时仅按容量清理；共用日志容量上限可能提前清理。</small>
                            </label>
                        </fieldset>
                        <div className="card-save-footer save-actions">
                            <button
                                className="btn btn-primary"
                                disabled={busy || !changed}
                                onClick={() => void save()}
                            >
                                <Save size={15} />
                                保存
                            </button>
                        </div>
                        {data.logs.activeBytes + data.logs.engineActiveBytes >
                            data.settings.logMaxTotalMb * 1024 ** 2 && (
                            <p className="action-notice">
                                正在写入的日志已超过容量上限，退出后将按策略清理。
                            </p>
                        )}
                    </section>
                    <section className="ui-card console-panel">
                        <div className="console-panel-heading">
                            <div>
                                <h2>文件清理</h2>
                                <p>删除旧日志或未使用的临时附件。</p>
                            </div>
                            <Trash2 size={18} />
                        </div>
                        <div className="storage-cleanup-row">
                            <div>
                                <strong>旧日志</strong>
                                <p>
                                    {data.logs.closedLaunches} 次历史运行 · 本次运行{' '}
                                    {bytes(data.logs.activeBytes)} · 引擎日志{' '}
                                    {data.logs.engineFiles} 个文件 {bytes(data.logs.engineBytes)}
                                </p>
                            </div>
                            <button
                                className="btn"
                                disabled={
                                    busy ||
                                    (!data.logs.closedLaunches && !data.logs.engineClosedFiles)
                                }
                                onClick={() =>
                                    void cleanup(
                                        { scope: 'logs' },
                                        '清理旧日志',
                                        '删除历史运行的日志和往日的引擎日志。本次运行与当天的引擎日志会保留。',
                                    )
                                }
                            >
                                <Trash2 size={15} />
                                清理
                            </button>
                        </div>
                        <div className="storage-cleanup-row">
                            <div>
                                <strong>临时文件</strong>
                                <p>{bytes(data.totals.temporaryBytes)} · 调试附件与媒体解码文件</p>
                            </div>
                            <button
                                className="btn"
                                disabled={busy || data.busy || !data.totals.temporaryBytes}
                                onClick={() =>
                                    void cleanup(
                                        { scope: 'temporary' },
                                        '清理临时文件',
                                        '删除暂存的调试附件和媒体解码文件，之后发送附件需要重新选择。',
                                    )
                                }
                            >
                                <Trash2 size={15} />
                                清理
                            </button>
                        </div>
                    </section>
                    <section className="ui-card console-panel">
                        <div className="console-panel-heading">
                            <div>
                                <h2>账号数据</h2>
                                <p>按分类清理；模型配置、人设和聊天范围会保留。</p>
                            </div>
                            <Database size={18} />
                        </div>
                        {data.busy && (
                            <p className="action-notice" role="status">
                                清理账号数据或临时文件前，请先断开 QQ、QQ Bot 与 WeChat Bot 连接，
                                等待当前任务停止后再刷新此页面。
                            </p>
                        )}
                        {!data.accounts.length ? (
                            <p className="action-notice">还没有账号数据。</p>
                        ) : (
                            <AnimatedList className="storage-accounts" staged>
                                {data.accounts.map((account) => (
                                    <div className="storage-account" key={account.account}>
                                        <div className="storage-account-heading">
                                            <strong>QQ {account.account}</strong>
                                            <span>
                                                {bytes(account.databaseBytes + account.indexBytes)}{' '}
                                                · 临时文件 {bytes(account.temporaryBytes)}
                                            </span>
                                        </div>
                                        <div className="storage-categories">
                                            {categories.map((category) => (
                                                <div className="storage-category" key={category.id}>
                                                    <div>
                                                        <strong>{category.label}</strong>
                                                        <p>{category.description}</p>
                                                        <small>
                                                            {category.id === 'indexes'
                                                                ? bytes(account.indexBytes)
                                                                : `${account.counts[category.id]} 条记录`}
                                                        </small>
                                                    </div>
                                                    <button
                                                        className="btn"
                                                        aria-label={`清理 ${account.account} 的${category.label}`}
                                                        disabled={
                                                            busy ||
                                                            data.busy ||
                                                            (category.id === 'indexes'
                                                                ? !account.indexFiles
                                                                : !account.counts[category.id])
                                                        }
                                                        onClick={() =>
                                                            void cleanup(
                                                                {
                                                                    scope: 'account',
                                                                    account: account.account,
                                                                    category: category.id,
                                                                },
                                                                `清理${category.label}`,
                                                                `删除 QQ ${account.account} 的${category.label}，无法撤销。${category.description}`,
                                                            )
                                                        }
                                                    >
                                                        <Trash2 size={15} />
                                                        清理
                                                    </button>
                                                </div>
                                            ))}
                                        </div>
                                    </div>
                                ))}
                            </AnimatedList>
                        )}
                        {data.accounts.length > 1 && (
                            <Disclosure title="批量清理">
                                <div className="storage-batch">
                                    {categories.map((category) => (
                                        <button
                                            className="btn"
                                            key={category.id}
                                            disabled={busy || data.busy}
                                            onClick={() =>
                                                void cleanup(
                                                    {
                                                        scope: 'allAccounts',
                                                        category: category.id,
                                                        accounts: data.accounts.map(
                                                            (item) => item.account,
                                                        ),
                                                    },
                                                    `清理全部${category.label}`,
                                                    `删除全部 ${data.accounts.length} 个账号的${category.label}，无法撤销。${category.description}`,
                                                )
                                            }
                                        >
                                            <Trash2 size={15} />
                                            清理全部{category.label}
                                        </button>
                                    ))}
                                </div>
                            </Disclosure>
                        )}
                    </section>
                    {data.lastCleanup && (
                        <p className="action-notice">
                            最近清理：{new Date(data.lastCleanup.at).toLocaleString()} ·{' '}
                            {data.lastCleanup.deletedRows} 条记录 · {data.lastCleanup.deletedFiles}{' '}
                            个文件 · 释放 {bytes(data.lastCleanup.freedBytes)}
                        </p>
                    )}
                </>
            )}
        </div>
    );
}
