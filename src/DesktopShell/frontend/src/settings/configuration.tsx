import { useConfirm } from '../components/confirmation';
import { useEffect, useRef, useState } from 'react';
import {
    Bot,
    List,
    Radio,
    Save,
    Plus,
    Trash2,
    Settings2,
    ShieldCheck,
    UserRound,
    Smile,
    Wrench,
} from 'lucide-react';
import type { BotConfig } from '../business';
import { draftApi, type Section, type SettingsDraft } from '../agent/settings-editor';
import { useSettings } from '../agent/use-settings';
import { Select } from '../components/select';
import { TokenLimit } from './token-limit';
import { Notice } from '../components/notice';
import { Disclosure } from '../components/disclosure';
import { ContactPicker } from '../agent/contacts-picker';
import { CheckDeadlineError, waitForCheck } from './check-deadline';

const groupTriggers = [
    { value: 'at', label: '被 @ 或引用机器人时处理' },
    { value: 'keywords', label: '被 @、引用机器人或命中关键词时处理' },
    { value: 'random', label: '被 @、引用、关键词或按概率处理' },
    { value: 'all', label: '每条新消息都处理' },
];

export function Configuration({
    ready,
    account,
    scope = 'bot',
    panel = 'model',
}: {
    ready: boolean;
    account?: string;
    scope?: 'bot' | 'global';
    panel?: 'model' | 'persona';
}) {
    const confirm = useConfirm();
    const { editor, state, error } = useSettings(ready, account, scope);
    const [models, setModels] = useState<string[]>([]);
    const [checking, setChecking] = useState<'list' | 'test' | 'tools' | null>(null);
    const [checkError, setCheckError] = useState('');
    const [checkNotice, setCheckNotice] = useState('');
    const [saveNotice, setSaveNotice] = useState('');
    const [loadingPersona, setLoadingPersona] = useState(false);
    const mounted = useRef(true),
        working = useRef(false);
    useEffect(() => {
        mounted.current = true;
        return () => {
            mounted.current = false;
        };
    }, []);
    useEffect(() => {
        setModels([]);
    }, [
        editor,
        state?.draft.profileId,
        state?.draft.config.api.baseUrl,
        state?.draft.config.api.protocol,
        state?.draft.key,
        state?.draft.clearKey,
    ]);
    useEffect(() => {
        setCheckError('');
        setCheckNotice('');
    }, [
        editor,
        state?.draft.profileId,
        state?.draft.config.api.baseUrl,
        state?.draft.config.api.protocol,
        state?.draft.config.api.model,
        state?.draft.key,
        state?.draft.clearKey,
    ]);
    useEffect(() => {
        setCheckError('');
        setCheckNotice('');
    }, [editor, state?.draft.config.webSearch]);
    const check = async (kind: 'list' | 'test' | 'tools') => {
        if (!editor || working.current) return;
        const draft = editor.getSnapshot().draft;
        const fingerprint = JSON.stringify([draftApi(draft), draft.profileId]);
        const current = () =>
            mounted.current &&
            fingerprint ===
                JSON.stringify([
                    draftApi(editor.getSnapshot().draft),
                    editor.getSnapshot().draft.profileId,
                ]);
        working.current = true;
        setChecking(kind);
        setCheckError('');
        setCheckNotice('');
        try {
            if (kind === 'list') {
                const result = await waitForCheck(
                    window.pywebview!.api.get_model_list(
                        scope === 'global' ? null : editor.account,
                        draftApi(draft),
                        draft.profileId,
                    ),
                    20000,
                );
                if (!current()) return;
                if (
                    result.ok &&
                    (scope === 'global'
                        ? result.scope === 'global'
                        : result.account === editor.account)
                ) {
                    setModels(result.models);
                    setCheckNotice(
                        result.models.length
                            ? `已获取 ${result.models.length} 个模型，可在模型名称中选择。`
                            : '服务未返回模型列表，仍可手动填写模型名称。',
                    );
                } else
                    setCheckError(
                        result.ok ? '连接账号已变化，请重新打开机器人设置' : result.error.message,
                    );
            } else {
                const result = await waitForCheck(
                    window.pywebview!.api.test_model_connection(
                        scope === 'global' ? null : editor.account,
                        draftApi(draft),
                        draft.profileId,
                        kind === 'tools' ? 'tools' : 'text',
                    ),
                    35000,
                );
                if (!current()) return;
                if (
                    result.ok &&
                    (scope === 'global'
                        ? result.scope === 'global'
                        : result.account === editor.account)
                )
                    setCheckNotice(
                        `${kind === 'tools' ? '工具调用与结果回填正常' : '基础连通正常'} · ${result.model} · ${result.latencyMs} 毫秒 · ${result.tokens} Token`,
                    );
                else
                    setCheckError(
                        result.ok ? '连接账号已变化，请重新打开机器人设置' : result.error.message,
                    );
            }
        } catch (error) {
            if (current())
                setCheckError(
                    error instanceof CheckDeadlineError
                        ? error.message
                        : '检查结果未确认，请稍后手动重试',
                );
        } finally {
            working.current = false;
            if (mounted.current) setChecking(null);
        }
    };
    if (!editor || !state)
        return (
            <section className="ui-card console-panel desktop-empty">
                <span className="empty-icon">
                    <Bot size={28} />
                </span>
                <h3>
                    {error ||
                        (ready
                            ? scope === 'global'
                                ? '正在读取全局设置'
                                : '请先连接机器人 QQ'
                            : '正在读取设置')}
                </h3>
                <p>
                    {scope === 'global'
                        ? '模型与联网由所有账号共用，无需连接 QQ。'
                        : '在「连接」页连接并核验账号后，可以配置人设和聊天范围。'}
                </p>
            </section>
        );
    const { config, key, clearKey, keywords, lists, profileId, profileName } = state.draft;
    const change = (patch: Partial<SettingsDraft>) => editor.change({ ...state.draft, ...patch });
    const setConfig = (value: BotConfig) => change({ config: value });
    const setKey = (value: string) => change({ key: value });
    const setClearKey = (value: boolean) => change({ clearKey: value });
    const setKeywords = (value: string) => change({ keywords: value });
    const setLists = (value: SettingsDraft['lists']) => change({ lists: value });
    const api = (field: keyof BotConfig['api'], value: string | number | boolean) =>
        setConfig({ ...config, api: { ...config.api, [field]: value } });
    const saveSection = async (section: Section, remove = false) => {
        setSaveNotice('');
        setCheckNotice('');
        setCheckError('');
        await editor.save(section, remove);
        if (mounted.current) {
            const latest = editor.getSnapshot();
            if (latest.errors[section]) setCheckError(latest.errors[section]!);
            else if (latest.saved === section)
                setSaveNotice(
                    remove
                        ? '配置已删除。'
                        : section === 'defaultPersona'
                          ? '默认人设已保存。'
                          : '已保存，自动回复已暂停。',
                );
        }
    };
    const toggleSticker = async (field: keyof BotConfig['sticker'], value: boolean) => {
        setSaveNotice('');
        setCheckNotice('');
        setCheckError('');
        await editor.toggleSticker(field, value);
        if (mounted.current) {
            const error = editor.getSnapshot().errors.sticker;
            error ? setCheckError(error) : setSaveNotice('已保存，自动回复已暂停。');
        }
    };
    const footer = (section: Section) => (
        <div className="card-save-footer save-actions">
            <button
                type="button"
                className="btn btn-primary"
                disabled={
                    Boolean(state.saving) ||
                    ((section === 'model' || section === 'search') && Boolean(checking)) ||
                    !editor.dirty(section)
                }
                onClick={() => void saveSection(section)}
            >
                <Save size={15} />
                保存
            </button>
        </div>
    );
    const pick = (id: string | null) => editor.pick(id);
    const applyDefaultPersona = async () => {
        if (loadingPersona || state.saving) return;
        setLoadingPersona(true);
        setCheckError('');
        setCheckNotice('');
        setSaveNotice('');
        const before = JSON.stringify(editor.getSnapshot().draft.config.persona);
        try {
            const result = await window.pywebview!.api.get_global_settings();
            if (!mounted.current) return;
            if (!result.ok) {
                setCheckError(result.error.message);
                return;
            }
            const latest = editor.getSnapshot().draft;
            if (JSON.stringify(latest.config.persona) !== before) {
                setCheckError('人设已发生变化，请再次点击使用默认人设。');
                return;
            }
            editor.change({
                ...latest,
                config: { ...latest.config, persona: { ...result.config.defaultPersona } },
            });
            setCheckNotice('已填入默认人设，可继续修改并保存。');
        } catch {
            if (mounted.current) setCheckError('读取默认人设失败，请稍后重试。');
        } finally {
            if (mounted.current) setLoadingPersona(false);
        }
    };
    return (
        <form onSubmit={(event) => event.preventDefault()} className="desktop-sections">
            <Notice
                message={checkError || checkNotice || saveNotice}
                title={saveNotice && !checkError && !checkNotice ? '保存完成' : undefined}
                error={Boolean(checkError)}
                onClose={() => {
                    setCheckError('');
                    setCheckNotice('');
                    setSaveNotice('');
                }}
            />
            {scope === 'global' && panel === 'model' && (
                <p className="action-notice">所有账号共用以下配置。</p>
            )}
            <fieldset className="desktop-sections bot-fieldset">
                {scope === 'global' && panel === 'persona' && (
                    <section className="ui-card console-panel">
                        <div className="console-panel-heading">
                            <div>
                                <h2>默认人设</h2>
                                <p>为新账号设置初始人设，也可在机器人设置中一键填入。</p>
                            </div>
                            <UserRound size={18} />
                        </div>
                        <div className="bot-form-grid">
                            <label className="form-wide">
                                角色设定
                                <textarea
                                    rows={14}
                                    value={config.defaultPersona.roleText}
                                    onChange={(e) =>
                                        setConfig({
                                            ...config,
                                            defaultPersona: {
                                                ...config.defaultPersona,
                                                roleText: e.target.value,
                                            },
                                        })
                                    }
                                />
                            </label>
                            <label className="form-wide">
                                补充规则
                                <textarea
                                    rows={3}
                                    value={config.defaultPersona.customRules}
                                    onChange={(e) =>
                                        setConfig({
                                            ...config,
                                            defaultPersona: {
                                                ...config.defaultPersona,
                                                customRules: e.target.value,
                                            },
                                        })
                                    }
                                />
                            </label>
                        </div>
                        {footer('defaultPersona')}
                    </section>
                )}
                {scope === 'global' && panel === 'model' && (
                    <>
                        {' '}
                        <section className="ui-card console-panel">
                            <div className="console-panel-heading">
                                <div>
                                    <h2>模型 API</h2>
                                    <p>
                                        当前使用：
                                        {state.config.profiles.find(
                                            (p) => p.id === state.config.activeProfileId,
                                        )?.name || '原有配置'}
                                    </p>
                                </div>
                                <Bot size={18} />
                            </div>
                            <div className="bot-form-grid">
                                <div className="bot-field">
                                    <span>模型配置</span>
                                    <Select
                                        label="模型配置"
                                        value={profileId || ''}
                                        options={[
                                            ...(!profileId || profileId === 'current'
                                                ? [{ value: profileId || '', label: profileName }]
                                                : []),
                                            ...state.config.profiles.map((p) => ({
                                                value: p.id,
                                                label: p.name,
                                            })),
                                        ]}
                                        onChange={(id) => pick(id)}
                                    />
                                </div>
                                <label>
                                    配置名称
                                    <input
                                        value={profileName}
                                        maxLength={64}
                                        onChange={(e) => change({ profileName: e.target.value })}
                                        placeholder="为这套模型配置命名"
                                    />
                                </label>
                                <div className="form-wide model-check-actions">
                                    <button
                                        type="button"
                                        className="btn"
                                        disabled={Boolean(state.saving)}
                                        onClick={() => pick(null)}
                                    >
                                        <Plus size={14} />
                                        新建配置
                                    </button>
                                    <button
                                        type="button"
                                        className="btn"
                                        disabled={
                                            !profileId ||
                                            profileId === 'current' ||
                                            profileId === state.config.activeProfileId ||
                                            Boolean(state.saving)
                                        }
                                        onClick={async () => {
                                            if (
                                                await confirm(
                                                    `删除配置“${profileName}”？此操作不会删除聊天记录。`,
                                                    {
                                                        title: '删除模型配置',
                                                        confirmLabel: '删除',
                                                        danger: true,
                                                    },
                                                )
                                            )
                                                void saveSection('model', true);
                                        }}
                                    >
                                        <Trash2 size={15} />
                                        删除此配置
                                    </button>
                                    <small>选择配置后，点击保存以启用。</small>
                                </div>
                                <div className="bot-field form-wide">
                                    <span>API 协议</span>
                                    <Select
                                        label="API 协议"
                                        value={config.api.protocol}
                                        options={[
                                            { value: 'chat', label: 'OpenAI · Chat Completions' },
                                            { value: 'responses', label: 'OpenAI · Responses' },
                                            { value: 'anthropic', label: 'Anthropic · Messages' },
                                        ]}
                                        onChange={(value) => api('protocol', value)}
                                    />
                                    <small>选择服务商要求的接口协议。</small>
                                </div>
                                <label>
                                    API 地址
                                    <input
                                        type="url"
                                        value={config.api.baseUrl}
                                        placeholder={
                                            config.api.protocol === 'anthropic'
                                                ? 'https://api.anthropic.com/v1'
                                                : 'https://api.example.com/v1'
                                        }
                                        onChange={(e) => api('baseUrl', e.target.value)}
                                    />
                                </label>
                                <div className="bot-field">
                                    <span>模型名称</span>
                                    <Select
                                        label="模型名称"
                                        editable
                                        value={config.api.model}
                                        options={models.map((model) => ({
                                            value: model,
                                            label: model,
                                        }))}
                                        placeholder="输入模型名称，或从列表选择"
                                        emptyText="尚未获取模型列表，可直接输入名称"
                                        onChange={(value) => api('model', value)}
                                    />
                                </div>
                                <div className="form-wide bot-field">
                                    <span>API 密钥</span>
                                    <div className="api-key-row">
                                        <input
                                            aria-label="API 密钥"
                                            type="password"
                                            value={clearKey ? '' : key}
                                            autoComplete="new-password"
                                            disabled={clearKey}
                                            placeholder={
                                                clearKey
                                                    ? '保存后清除密钥'
                                                    : config.api.apiKeyConfigured
                                                      ? '已保存，输入新密钥可替换'
                                                      : '填写 API 密钥'
                                            }
                                            onChange={(e) => setKey(e.target.value)}
                                        />
                                        <button
                                            type="button"
                                            className="btn"
                                            disabled={!config.api.apiKeyConfigured && !clearKey}
                                            onClick={() => setClearKey(!clearKey)}
                                        >
                                            <Trash2 size={15} />
                                            {clearKey ? '撤销清除' : '清除密钥'}
                                        </button>
                                    </div>
                                </div>
                                <div className="form-wide model-check-actions">
                                    <button
                                        type="button"
                                        className="btn"
                                        disabled={Boolean(checking) || !config.api.baseUrl}
                                        onClick={() => void check('list')}
                                    >
                                        <List
                                            size={15}
                                            className={
                                                checking === 'list' ? 'qq-scanning' : undefined
                                            }
                                        />
                                        获取模型列表
                                    </button>
                                    <button
                                        type="button"
                                        className="btn"
                                        disabled={
                                            Boolean(checking) ||
                                            !config.api.baseUrl ||
                                            !config.api.model
                                        }
                                        onClick={() => void check('test')}
                                    >
                                        <Radio
                                            size={15}
                                            className={
                                                checking === 'test' ? 'qq-scanning' : undefined
                                            }
                                        />
                                        基础连通性
                                    </button>
                                    <button
                                        type="button"
                                        className="btn"
                                        disabled={
                                            Boolean(checking) ||
                                            !config.api.baseUrl ||
                                            !config.api.model
                                        }
                                        onClick={() => void check('tools')}
                                    >
                                        <Wrench
                                            size={15}
                                            className={
                                                checking === 'tools' ? 'qq-scanning' : undefined
                                            }
                                        />
                                        测试工具调用
                                    </button>
                                </div>
                                <div className="form-wide model-subheading">
                                    <h3>高级模型参数</h3>
                                </div>
                                <label className="form-wide form-check">
                                    <input
                                        type="checkbox"
                                        checked={config.api.sendTemperature}
                                        onChange={(e) => api('sendTemperature', e.target.checked)}
                                    />
                                    发送 Temperature 参数（模型不支持时关闭）
                                </label>
                                <label>
                                    回复变化程度（Temperature）
                                    <input
                                        type="number"
                                        min={0}
                                        max={2}
                                        step={0.1}
                                        value={config.api.temperature}
                                        disabled={!config.api.sendTemperature}
                                        onChange={(e) => api('temperature', Number(e.target.value))}
                                    />
                                    <small>越低越稳定，越高越多变。</small>
                                </label>
                                <label>
                                    工具调用轮数上限
                                    <input
                                        type="number"
                                        min={1}
                                        max={20}
                                        value={config.api.maxRounds}
                                        onChange={(e) => api('maxRounds', Number(e.target.value))}
                                    />
                                    <small>一次处理最多允许模型连续调用工具的轮数。</small>
                                </label>
                                <TokenLimit api={config.api} onChange={api} />
                                <label>
                                    请求超时（秒）
                                    <input
                                        type="number"
                                        min={1}
                                        max={300}
                                        value={config.api.timeoutMs / 1000}
                                        onChange={(e) =>
                                            api('timeoutMs', Number(e.target.value) * 1000)
                                        }
                                    />
                                    <small>等待单次模型响应的最长时间。</small>
                                </label>
                            </div>
                            {footer('model')}
                        </section>
                    </>
                )}
                {scope === 'bot' && (
                    <>
                        {' '}
                        <section className="ui-card console-panel">
                            <div className="console-panel-heading">
                                <div>
                                    <h2>表情库</h2>
                                    <p>
                                        让机器人收藏和使用聊天图片；需在系统设置的“图片处理”中开启看图，发送表情还需开启发图。
                                    </p>
                                </div>
                                <Smile size={18} />
                            </div>
                            <div className="bot-form-grid">
                                <label className="form-wide form-check">
                                    <input
                                        type="checkbox"
                                        checked={config.sticker.enabled}
                                        disabled={Boolean(state.saving)}
                                        onChange={(e) =>
                                            void toggleSticker('enabled', e.target.checked)
                                        }
                                    />
                                    允许机器人使用本地表情库
                                </label>
                                <label className="form-wide form-check">
                                    <input
                                        type="checkbox"
                                        checked={config.sticker.collectEnabled}
                                        disabled={Boolean(state.saving)}
                                        onChange={(e) =>
                                            void toggleSticker('collectEnabled', e.target.checked)
                                        }
                                    />
                                    允许模型看图确认后收藏当前聊天图片
                                </label>
                                <label className="form-wide form-check">
                                    <input
                                        type="checkbox"
                                        checked={Boolean(config.sticker.allowPoke)}
                                        disabled={Boolean(state.saving)}
                                        onChange={(e) =>
                                            void toggleSticker('allowPoke', e.target.checked)
                                        }
                                    />
                                    允许拍一拍（每次处理最多一次）
                                </label>
                            </div>
                        </section>
                        <section className="ui-card console-panel">
                            <div className="console-panel-heading">
                                <div>
                                    <h2>人设与规则</h2>
                                    <p>设置机器人的角色、说话方式和补充规则</p>
                                </div>
                                <UserRound size={18} />
                            </div>
                            <div className="bot-form-grid">
                                <div className="form-wide">
                                    <button
                                        type="button"
                                        className="btn"
                                        disabled={loadingPersona || Boolean(state.saving)}
                                        onClick={() => void applyDefaultPersona()}
                                    >
                                        <UserRound
                                            size={15}
                                            className={loadingPersona ? 'qq-scanning' : undefined}
                                        />
                                        使用默认人设
                                    </button>
                                    <p className="action-notice">
                                        填入系统设置中的角色设定和补充规则，修改后请保存。
                                    </p>
                                </div>
                                <label className="form-wide">
                                    角色设定
                                    <textarea
                                        rows={5}
                                        value={config.persona.roleText}
                                        onChange={(e) =>
                                            setConfig({
                                                ...config,
                                                persona: {
                                                    ...config.persona,
                                                    roleText: e.target.value,
                                                },
                                            })
                                        }
                                    />
                                </label>
                                <label className="form-wide">
                                    补充规则
                                    <textarea
                                        rows={3}
                                        value={config.persona.customRules}
                                        onChange={(e) =>
                                            setConfig({
                                                ...config,
                                                persona: {
                                                    ...config.persona,
                                                    customRules: e.target.value,
                                                },
                                            })
                                        }
                                    />
                                </label>
                            </div>
                            {footer('persona')}
                        </section>
                        <section className="ui-card console-panel">
                            <div className="console-panel-heading">
                                <div>
                                    <h2>聊天范围</h2>
                                    <p>
                                        填写允许接入的群号和用户编号，多个号码用换行或逗号分隔；留空则不接入。
                                    </p>
                                </div>
                                <ShieldCheck size={18} />
                            </div>
                            <div className="bot-form-grid">
                                <ContactPicker editor={editor} />
                                <label>
                                    群聊白名单
                                    <textarea
                                        rows={4}
                                        value={lists.groups}
                                        onChange={(e) =>
                                            setLists({ ...lists, groups: e.target.value })
                                        }
                                    />
                                </label>
                                <label>
                                    好友白名单
                                    <textarea
                                        rows={4}
                                        value={lists.private}
                                        onChange={(e) =>
                                            setLists({ ...lists, private: e.target.value })
                                        }
                                    />
                                </label>
                                <div className="bot-field">
                                    <span>群聊触发</span>
                                    <Select
                                        label="群聊触发"
                                        value={config.groupTrigger}
                                        options={groupTriggers}
                                        onChange={(value) =>
                                            setConfig({
                                                ...config,
                                                groupTrigger: value as BotConfig['groupTrigger'],
                                            })
                                        }
                                    />
                                </div>
                                <label>
                                    上下文消息条数
                                    <input
                                        type="number"
                                        min={1}
                                        max={200}
                                        value={config.contextLimit}
                                        onChange={(e) =>
                                            setConfig({
                                                ...config,
                                                contextLimit: Number(e.target.value),
                                            })
                                        }
                                    />
                                </label>
                                {config.groupTrigger === 'random' && (
                                    <label className="form-wide">
                                        普通群消息触发概率（%）
                                        <input
                                            type="number"
                                            min={0}
                                            max={100}
                                            step={1}
                                            required
                                            value={config.groupRandomPercent}
                                            onChange={(e) =>
                                                setConfig({
                                                    ...config,
                                                    groupRandomPercent: Number(e.target.value),
                                                })
                                            }
                                        />
                                        <small>
                                            除 @、引用和关键词外，其他群消息按此概率触发。
                                        </small>
                                    </label>
                                )}
                                {(config.groupTrigger === 'keywords' ||
                                    config.groupTrigger === 'random') && (
                                    <label className="form-wide">
                                        群聊关键词
                                        <textarea
                                            rows={3}
                                            value={keywords}
                                            placeholder="输入关键词，每行一个"
                                            onChange={(e) => setKeywords(e.target.value)}
                                        />
                                        <small>
                                            群消息包含任一关键词时触发，不区分英文大小写。
                                        </small>
                                    </label>
                                )}
                            </div>
                            {footer('scope')}
                        </section>
                        <section className="ui-card console-panel">
                            <Disclosure
                                title={
                                    <span className="bot-advanced-title">
                                        <Settings2 size={17} />
                                        高级设置
                                    </span>
                                }
                            >
                                <div className="bot-form-grid">
                                    <label>
                                        群聊黑名单
                                        <textarea
                                            rows={3}
                                            value={lists.denyGroups}
                                            onChange={(e) =>
                                                setLists({ ...lists, denyGroups: e.target.value })
                                            }
                                        />
                                    </label>
                                    <label>
                                        好友黑名单
                                        <textarea
                                            rows={3}
                                            value={lists.denyPrivate}
                                            onChange={(e) =>
                                                setLists({ ...lists, denyPrivate: e.target.value })
                                            }
                                        />
                                    </label>
                                    <label className="form-wide">
                                        忽略这些成员
                                        <textarea
                                            rows={2}
                                            value={lists.blocked}
                                            onChange={(e) =>
                                                setLists({ ...lists, blocked: e.target.value })
                                            }
                                        />
                                    </label>
                                </div>
                            </Disclosure>
                            {footer('advanced')}
                        </section>
                    </>
                )}
            </fieldset>
        </form>
    );
}
