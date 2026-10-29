import { useEffect, useRef, useState } from 'react';
import { Image, Save, Radio, List, SquarePen, Trash2 } from 'lucide-react';
import type { BotConfig } from '../business';
import { Select } from '../components/select';
import { Collapse } from '../components/presence';
import { TokenLimit } from './token-limit';
import { Notice } from '../components/notice';
import { blankApi } from '../agent/settings-editor';
import { CheckDeadlineError, waitForCheck } from './check-deadline';

type Media = BotConfig['mediaOptions'];
type Profile = BotConfig['profiles'][number];
type ProfileChange = {
    field: 'imageProfileId';
    data: { id: string | null; name: string; api: unknown };
    onStored: (id: string) => void;
};
type Writer = (patch: Partial<Media>, profile?: ProfileChange) => Promise<BotConfig | null>;
export function MediaSettings({ ready }: { ready: boolean }) {
    const [config, setConfig] = useState<BotConfig | null>(null),
        [busy, setBusy] = useState(false),
        [notice, setNotice] = useState(''),
        [error, setError] = useState('');
    const alive = useRef(true),
        working = useRef(false);
    useEffect(() => {
        alive.current = true;
        return () => {
            alive.current = false;
        };
    }, []);
    useEffect(() => {
        if (!ready) return;
        let active = true;
        void window
            .pywebview!.api.get_global_settings()
            .then((r) => {
                if (active) {
                    if (r.ok) setConfig(r.config);
                    else setError(r.error.message);
                }
            })
            .catch(() => {
                if (active) setError('媒体设置读取失败');
            });
        return () => {
            active = false;
        };
    }, [ready]);
    const write: Writer = async (patch, profile) => {
        if (working.current) return null;
        working.current = true;
        setBusy(true);
        setError('');
        setNotice('');
        try {
            if (profile) {
                const before = new Set(config?.profiles.map((p) => p.id));
                const stored = await window.pywebview!.api.manage_model_profile(
                    'store',
                    profile.data,
                    null,
                );
                if (!alive.current) return null;
                if (!stored.ok) {
                    setError(stored.error.message);
                    return null;
                }
                setConfig(stored.config);
                const id =
                    profile.data.id || stored.config.profiles.find((p) => !before.has(p.id))?.id;
                if (!id) {
                    setError('新配置编号未确认，请刷新模型目录检查');
                    return null;
                }
                profile.onStored(id);
                patch = { ...patch, [profile.field]: id };
            }
            const r = await window.pywebview!.api.save_global_settings({ mediaOptions: patch });
            if (!alive.current) return null;
            if (!r.ok) {
                setError(r.error.message);
                return null;
            }
            setConfig(r.config);
            setNotice('已保存，自动回复已暂停。');
            return r.config;
        } catch {
            if (alive.current) setError('保存结果未确认，请刷新检查；没有自动重试');
            return null;
        } finally {
            working.current = false;
            if (alive.current) setBusy(false);
        }
    };
    const toggle = async (field: 'vision' | 'sendImages', value: boolean) => {
        if (!config || working.current) return;
        const previous = config;
        // Turning vision off also retracts its dependent toggles so the stored
        // config can never keep sendImages enabled without vision.
        const patch: Partial<Media> =
            field === 'vision' && !value
                ? { vision: false, sendImages: false }
                : { [field]: value };
        setConfig({ ...config, mediaOptions: { ...config.mediaOptions, ...patch } });
        const result = await write(patch);
        if (!result && alive.current) setConfig(previous);
    };
    if (!config)
        return (
            <section className="ui-card console-panel">
                <Notice error message={error} onClose={() => setError('')} />
                <h2>正在读取媒体设置</h2>
            </section>
        );
    const options = config.mediaOptions;
    return (
        <div className="desktop-sections">
            <Notice
                title={error ? '操作未完成' : '媒体设置'}
                message={error || notice}
                error={Boolean(error)}
                onClose={() => {
                    setError('');
                    setNotice('');
                }}
            />
            <section className="ui-card console-panel">
                <div className="console-panel-heading">
                    <div>
                        <h2>图片功能</h2>
                        <p>所有账号共用。动图只读第一帧；发图需先开启看图。</p>
                    </div>
                    <Image size={18} />
                </div>
                <div className="bot-form-grid">
                    {(
                        [
                            ['vision', '允许模型查看聊天图片'],
                            ['sendImages', '允许机器人发送图片'],
                        ] as const
                    ).map(([field, label]) => (
                        <label className="form-wide form-check" key={field}>
                            <input
                                type="checkbox"
                                checked={options[field]}
                                disabled={busy || (field !== 'vision' && !options.vision)}
                                onChange={(e) => void toggle(field, e.target.checked)}
                            />
                            {label}
                        </label>
                    ))}
                </div>
            </section>
            <MediaModel
                config={config}
                busy={busy}
                write={write}
                feedback={(message, failed = false) => {
                    setError(failed ? message : '');
                    setNotice(failed ? '' : message);
                }}
            />
        </div>
    );
}

function MediaModel({
    config,
    busy,
    write,
    feedback,
}: {
    config: BotConfig;
    busy: boolean;
    write: Writer;
    feedback: (message: string, failed?: boolean) => void;
}) {
    const field = 'imageProfileId',
        label = '看图模型';
    const [selected, select] = useState(config.mediaOptions[field]),
        [editing, setEditing] = useState(false),
        [api, setApi] = useState({ ...blankApi }),
        [name, setName] = useState(''),
        [key, setKey] = useState(''),
        [clear, setClear] = useState(false);
    const [models, setModels] = useState<string[]>([]),
        [checking, setChecking] = useState<'list' | 'image' | null>(null),
        [saving, setSaving] = useState(false);
    const [elapsed, setElapsed] = useState(0);
    useEffect(() => {
        if (!checking) return;
        const started = performance.now();
        setElapsed(0);
        const timer = window.setInterval(
            () => setElapsed(Math.floor((performance.now() - started) / 1000)),
            1000,
        );
        return () => window.clearInterval(timer);
    }, [checking]);
    const setError = (message: string) => feedback(message, true),
        setNotice = (message: string) => feedback(message);
    const alive = useRef(true),
        working = useRef(false);
    useEffect(() => {
        alive.current = true;
        return () => {
            alive.current = false;
        };
    }, []);
    const drafts = useRef(
        new Map<
            string,
            { editing: boolean; api: BotConfig['api']; name: string; key: string; clear: boolean }
        >(),
    );
    const current = config.profiles.find((p) => p.id === selected);
    const inheritedId = config.activeProfileId || 'current';
    const inherited = config.profiles.find((p) => p.id === inheritedId);
    const inheritedName = inherited?.name || '当前聊天配置';
    const summaryApi = current?.api || inherited?.api || config.api;
    const protocolName = {
        chat: 'Chat Completions',
        responses: 'Responses',
        anthropic: 'Anthropic Messages',
    }[summaryApi.protocol];
    const choose = (id: string) => {
        if (id === selected) return;
        drafts.current.set(selected, { editing, api, name, key, clear });
        select(id);
        const cached = drafts.current.get(id);
        setEditing(cached?.editing ?? id === 'new');
        setApi(cached?.api ?? { ...blankApi });
        setKey(cached?.key ?? '');
        setClear(cached?.clear ?? false);
        setName(cached?.name ?? '图片配置');
        setModels([]);
        setNotice('');
        setError('');
    };
    const edit = (profile: Profile) => {
        setEditing(true);
        setApi({ ...profile.api });
        setName(profile.name);
        setKey('');
        setClear(false);
        setModels([]);
    };
    const draft = () => {
        const { apiKeyConfigured: _, ...values } = api;
        return { ...values, ...(clear ? { apiKey: '' } : key ? { apiKey: key } : {}) };
    };
    const check = async (list: boolean) => {
        if (working.current) return;
        working.current = true;
        setChecking(list ? 'list' : 'image');
        setNotice('');
        setError('');
        try {
            const source = editing ? draft() : undefined,
                id = selected === 'new' ? null : selected || inheritedId;
            const request = list
                ? window.pywebview!.api.get_model_list(null, source, id)
                : window.pywebview!.api.test_model_connection(null, source, id, 'image');
            const r = await waitForCheck(request, list ? 20000 : 35000);
            if (!alive.current) return;
            if (!r.ok) {
                setError(r.error.message);
                return;
            }
            if ('models' in r) {
                setModels(r.models);
                setNotice(`已获取 ${r.models.length} 个模型。`);
            } else setNotice(`媒体输入连通成功 · ${r.model} · ${r.latencyMs} 毫秒 · ${r.reply}`);
        } catch (error) {
            if (alive.current)
                setError(
                    error instanceof CheckDeadlineError
                        ? error.message
                        : '检查结果未确认，请手动检查配置',
                );
        } finally {
            working.current = false;
            if (alive.current) setChecking(null);
        }
    };
    const save = async () => {
        if (working.current || busy) return;
        working.current = true;
        setSaving(true);
        setError('');
        setNotice('');
        try {
            const change: ProfileChange | undefined = editing
                ? {
                      field,
                      data: { id: selected === 'new' ? null : selected, name, api: draft() },
                      onStored: (id) => {
                          drafts.current.delete(selected);
                          drafts.current.delete(id);
                          if (alive.current) {
                              select(id);
                              setEditing(false);
                              setKey('');
                              setClear(false);
                          }
                      },
                  }
                : undefined;
            await write(editing ? {} : { [field]: selected }, change);
        } catch {
            if (alive.current) setError('保存结果未确认，请刷新模型目录检查，不会自动重试');
        } finally {
            working.current = false;
            if (alive.current) setSaving(false);
        }
    };
    const disabled = busy || Boolean(checking) || saving;
    return (
        <section className="ui-card console-panel" aria-label={label}>
            <div className="console-panel-heading">
                <div>
                    <h2>{label}</h2>
                    <p>未指定时使用聊天模型。</p>
                </div>
                <Image size={18} />
            </div>
            <fieldset className="bot-fieldset bot-form-grid" disabled={disabled}>
                <div className="bot-field form-wide">
                    <span>配置来源</span>
                    <div className="media-profile-control">
                        <Select
                            label={label + '配置来源'}
                            disabled={disabled}
                            value={selected}
                            onChange={choose}
                            options={[
                                { value: '', label: '默认 · 使用聊天模型' },
                                ...config.profiles.map((p) => ({ value: p.id, label: p.name })),
                                { value: 'new', label: '新建独立配置…' },
                            ]}
                        />
                        {current && !editing && (
                            <button type="button" className="btn" onClick={() => edit(current)}>
                                <SquarePen size={15} />
                                编辑此配置
                            </button>
                        )}
                    </div>
                </div>
                {(!selected || current) && !editing && (
                    <div className="form-wide media-model-summary">
                        <div className="media-model-summary-heading">
                            <span>{selected ? '当前模型' : `继承自 ${inheritedName}`}</span>
                            <strong>{summaryApi.model || '尚未配置模型'}</strong>
                        </div>
                        <div className="media-model-summary-meta">
                            <span>{protocolName}</span>
                            {summaryApi.baseUrl && (
                                <span className="media-model-endpoint">{summaryApi.baseUrl}</span>
                            )}
                        </div>
                    </div>
                )}
                <Collapse open={editing}>
                    <div className="form-wide">
                        <div className="bot-form-grid">
                            <label>
                                配置名称
                                <input
                                    value={name}
                                    maxLength={64}
                                    onChange={(e) => setName(e.target.value)}
                                />
                            </label>
                            <div className="bot-field">
                                <span>API 协议</span>
                                <Select
                                    label={label + 'API 协议'}
                                    value={api.protocol}
                                    disabled={disabled}
                                    onChange={(value) =>
                                        setApi({
                                            ...api,
                                            protocol: value as typeof api.protocol,
                                        })
                                    }
                                    options={[
                                        { value: 'chat', label: 'Chat Completions' },
                                        { value: 'responses', label: 'Responses' },
                                        { value: 'anthropic', label: 'Anthropic Messages' },
                                    ]}
                                />
                            </div>
                            <label className="form-wide">
                                API 地址
                                <input
                                    type="url"
                                    value={api.baseUrl}
                                    onChange={(e) => setApi({ ...api, baseUrl: e.target.value })}
                                    placeholder="https://api.example.com/v1"
                                />
                            </label>
                            <div className="bot-field form-wide">
                                <span>模型名称</span>
                                <Select
                                    label={label + '名称'}
                                    editable
                                    disabled={disabled}
                                    value={api.model}
                                    onChange={(model) => setApi({ ...api, model })}
                                    options={models.map((value) => ({ value, label: value }))}
                                />
                            </div>
                            <div className="bot-field form-wide">
                                <span>API 密钥</span>
                                <div className="api-key-row">
                                    <input
                                        aria-label={label + 'API 密钥'}
                                        type="password"
                                        autoComplete="new-password"
                                        maxLength={8192}
                                        disabled={clear}
                                        value={clear ? '' : key}
                                        placeholder={
                                            clear
                                                ? '保存后清除密钥'
                                                : api.apiKeyConfigured
                                                  ? '已保存密钥；填写新值可替换'
                                                  : '填写密钥'
                                        }
                                        onChange={(e) => setKey(e.target.value)}
                                    />
                                    <button
                                        type="button"
                                        className="btn"
                                        onClick={() => setClear(!clear)}
                                    >
                                        <Trash2 size={15} />
                                        {clear ? '撤销清除' : '清除密钥'}
                                    </button>
                                </div>
                            </div>
                            <label className="form-wide form-check">
                                <input
                                    type="checkbox"
                                    checked={api.sendTemperature}
                                    onChange={(e) =>
                                        setApi({ ...api, sendTemperature: e.target.checked })
                                    }
                                />
                                发送 Temperature 参数
                            </label>
                            <label>
                                Temperature
                                <input
                                    type="number"
                                    min={0}
                                    max={2}
                                    step={0.1}
                                    value={api.temperature}
                                    disabled={!api.sendTemperature}
                                    onChange={(e) =>
                                        setApi({ ...api, temperature: Number(e.target.value) })
                                    }
                                />
                            </label>
                            <label>
                                请求超时（秒）
                                <input
                                    type="number"
                                    min={1}
                                    max={300}
                                    value={api.timeoutMs / 1000}
                                    onChange={(e) =>
                                        setApi({
                                            ...api,
                                            timeoutMs: Number(e.target.value) * 1000,
                                        })
                                    }
                                />
                            </label>
                            <TokenLimit
                                api={api}
                                onChange={(field, value) => setApi({ ...api, [field]: value })}
                            />
                        </div>
                    </div>
                </Collapse>
                <div className="form-wide model-check-actions">
                    {editing && (
                        <button type="button" className="btn" onClick={() => void check(true)}>
                            <List
                                size={15}
                                className={checking === 'list' ? 'qq-scanning' : undefined}
                            />
                            获取模型列表
                        </button>
                    )}
                    <button type="button" className="btn" onClick={() => void check(false)}>
                        <Radio
                            size={15}
                            className={checking === 'image' ? 'qq-scanning' : undefined}
                        />
                        测试图片输入
                    </button>
                    <small role={checking ? 'status' : undefined}>
                        {checking
                            ? `已等待 ${elapsed} 秒，最多 ${checking === 'list' ? 15 : 30} 秒。`
                            : '用测试图片检查模型的识图能力。'}
                    </small>
                </div>
            </fieldset>
            {editing && current && (
                <p className="action-notice">编辑此配置会同时影响引用它的其他用途。</p>
            )}
            <div className="card-save-footer save-actions">
                <button
                    type="button"
                    disabled={disabled}
                    className="btn btn-primary"
                    onClick={() => void save()}
                >
                    <Save size={15} />
                    保存
                </button>
            </div>
        </section>
    );
}
