import { useEffect, useRef, useState } from 'react';
import { Check, CircleAlert, FileText, Globe, Play, Save, Search } from 'lucide-react';
import type { NetworkProbe } from '../desktop';
import { useSettings } from '../agent/use-settings';
import { Select } from '../components/select';
import { Disclosure } from '../components/disclosure';
import { Collapse } from '../components/presence';
import { Notice } from '../components/notice';

export function NetworkSettings({ ready }: { ready: boolean }) {
    const { editor, state, error } = useSettings(ready, undefined, 'global');
    const [kind, setKind] = useState<'search' | 'fetch'>('search');
    const [query, setQuery] = useState(''),
        [url, setUrl] = useState('');
    const [busy, setBusy] = useState(false),
        [result, setResult] = useState<NetworkProbe | null>(null);
    const [notice, setNotice] = useState(''),
        [failed, setFailed] = useState(false);
    const mounted = useRef(true),
        working = useRef(false),
        revision = useRef(0);
    const config = state?.draft.config.webSearch;
    useEffect(() => {
        mounted.current = true;
        return () => {
            mounted.current = false;
        };
    }, []);
    useEffect(() => {
        revision.current++;
        setResult(null);
    }, [kind, query, url, config]);
    if (!editor || !state || !config)
        return (
            <section className="ui-card console-panel desktop-empty">
                <Globe size={28} />
                <h3>{error || '正在读取联网设置'}</h3>
            </section>
        );
    const change = (patch: Partial<typeof config>) =>
        editor.change({
            ...editor.getSnapshot().draft,
            config: { ...editor.getSnapshot().draft.config, webSearch: { ...config, ...patch } },
        });
    const save = async () => {
        setNotice('');
        await editor.save('search');
        if (!mounted.current) return;
        const message = editor.getSnapshot().errors.search;
        setFailed(Boolean(message));
        setNotice(message || '已保存');
    };
    const test = async () => {
        if (working.current) return;
        working.current = true;
        setBusy(true);
        setResult(null);
        setNotice('');
        const version = revision.current;
        try {
            const r = await window.pywebview!.api.test_web_search(
                null,
                { ...config },
                { kind, value: kind === 'search' ? query : url },
            );
            if (!mounted.current || revision.current !== version) return;
            if (r.ok && r.scope === 'global') setResult(r);
            else {
                setFailed(true);
                setNotice(r.ok ? '配置范围已变化，请重新打开联网设置' : r.error.message);
            }
        } catch {
            if (mounted.current && revision.current === version) {
                setFailed(true);
                setNotice('测试未完成，请检查运行日志');
            }
        } finally {
            working.current = false;
            if (mounted.current) setBusy(false);
        }
    };
    const attempts = result?.result?.attempts || result?.attempts || [];
    return (
        <div className="desktop-sections">
            <Notice message={notice} error={failed} onClose={() => setNotice('')} />
            <section className="ui-card console-panel">
                <div className="console-panel-heading">
                    <div>
                        <h2>联网搜索</h2>
                        <p>先搜索 Bing 和百度，均失败后可使用所选模型的原生联网搜索。</p>
                    </div>
                    <Globe size={18} />
                </div>
                <div className="bot-form-grid">
                    <label className="form-wide form-check">
                        <input
                            type="checkbox"
                            checked={config.enabled}
                            onChange={(e) => change({ enabled: e.target.checked })}
                        />
                        允许机器人联网
                    </label>
                    <label className="form-wide form-check">
                        <input
                            type="checkbox"
                            checked={config.browse}
                            onChange={(e) => change({ browse: e.target.checked })}
                        />
                        允许读取网页正文
                    </label>
                    <div className="bot-field">
                        <span>本地搜索结果条数</span>
                        <Select
                            label="本地搜索结果条数"
                            value={String(config.maxResults)}
                            onChange={(value) => change({ maxResults: Number(value) })}
                            options={[1, 2, 3, 4, 5, 6, 7, 8, 9, 10].map((n) => ({
                                value: String(n),
                                label: `${n} 条`,
                            }))}
                        />
                    </div>
                    <label className="form-wide form-check">
                        <input
                            type="checkbox"
                            checked={config.fallbackEnabled}
                            disabled={!state.config.profiles.length}
                            onChange={(e) => change({ fallbackEnabled: e.target.checked })}
                        />
                        本地搜索失败时使用模型搜索
                    </label>
                    <div className="bot-field form-wide">
                        <span>搜索模型配置</span>
                        <Select
                            label="搜索模型配置"
                            value={config.fallbackProfileId}
                            onChange={(value) => change({ fallbackProfileId: value })}
                            options={[
                                { value: '', label: '请选择已保存的配置' },
                                ...state.config.profiles.map((profile) => ({
                                    value: profile.id,
                                    label: `${profile.name} · ${profile.api.model || '未填写模型'} · ${profile.api.protocol}`,
                                })),
                            ]}
                        />
                        <small>
                            {state.config.profiles.length
                                ? '所选服务商和模型须支持原生联网搜索；不会切换聊天模型。'
                                : '先在模型 API 页面保存支持联网搜索的配置。'}
                        </small>
                    </div>
                </div>
                <div className="card-save-footer save-actions">
                    <button
                        className="btn btn-primary"
                        disabled={Boolean(state.saving) || !editor.dirty('search')}
                        onClick={() => void save()}
                    >
                        <Save size={15} />
                        保存
                    </button>
                </div>
            </section>
            <section className="ui-card console-panel">
                <div className="console-panel-heading">
                    <div>
                        <h2>联网测试</h2>
                        <p>填写关键词或网页地址，检查实际取得的内容。</p>
                    </div>
                    {kind === 'search' ? <Search size={18} /> : <FileText size={18} />}
                </div>
                <form
                    onSubmit={(e) => {
                        e.preventDefault();
                        void test();
                    }}
                    className="bot-form-grid"
                >
                    <div className="bot-field">
                        <span>测试内容</span>
                        <Select
                            label="联网测试类型"
                            value={kind}
                            options={[
                                { value: 'search', label: '搜索关键词' },
                                { value: 'fetch', label: '读取网页' },
                            ]}
                            onChange={(value) => setKind(value as typeof kind)}
                        />
                    </div>
                    <label>
                        {kind === 'search' ? '关键词' : '网页地址'}
                        <input
                            value={kind === 'search' ? query : url}
                            maxLength={kind === 'search' ? 120 : 4096}
                            onChange={(e) =>
                                kind === 'search'
                                    ? setQuery(e.target.value)
                                    : setUrl(e.target.value)
                            }
                            placeholder={kind === 'search' ? '输入你实际想搜索的内容' : 'https://…'}
                        />
                    </label>
                    <div className="form-wide model-check-actions">
                        <button
                            type="submit"
                            className="btn"
                            disabled={busy || !(kind === 'search' ? query : url).trim()}
                        >
                            <Play size={14} />
                            {busy ? '正在测试…' : '开始测试'}
                        </button>
                        {busy && <span className="action-notice">正在等待网站返回内容</span>}
                    </div>
                </form>
                <Collapse open={Boolean(result)}>
                    {result && (
                        <div
                            key={`${result.kind}:${result.value}`}
                            className="network-result page-enter"
                        >
                            <div className="network-result-body">
                                <div className="tool-heading">
                                    <strong>{result.success ? '已取得内容' : '未取得内容'}</strong>
                                    <small>{(result.elapsedMs / 1000).toFixed(1)} 秒</small>
                                </div>
                                {!result.success && (
                                    <p role="alert" className="desktop-error">
                                        {result.message}
                                    </p>
                                )}
                                {result.result?.mode === 'provider' && (
                                    <p className="action-notice">
                                        模型搜索 · {result.result.model} ·{' '}
                                        {result.result.usage?.totalTokens ?? 0} Token
                                    </p>
                                )}
                                {result.result?.results?.map((item, index) => (
                                    <article key={item.url} className="network-source">
                                        <strong>
                                            {index + 1}. {item.title}
                                        </strong>
                                        <small>{item.url}</small>
                                        <p>{item.snippet || '此结果没有摘要，可读取来源网页。'}</p>
                                        <button
                                            className="btn"
                                            disabled={busy}
                                            onClick={() => {
                                                setUrl(item.url);
                                                setKind('fetch');
                                            }}
                                        >
                                            读取此网页
                                        </button>
                                    </article>
                                ))}
                                {result.result?.content && (
                                    <>
                                        <h3>{result.result.title || '网页正文'}</h3>
                                        <p className="network-source-url">{result.result.url}</p>
                                        <pre className="network-page-text">
                                            {result.result.content}
                                        </pre>
                                        {result.result.truncated && (
                                            <small>正文较长，显示前 12000 字。</small>
                                        )}
                                    </>
                                )}
                                {attempts.length > 0 && (
                                    <Disclosure className="network-process" title="搜索过程">
                                        <ol className="network-attempts">
                                            {attempts.map((attempt, index) => (
                                                <li
                                                    key={index}
                                                    className={
                                                        'network-attempt ' +
                                                        (attempt.status === 'ok'
                                                            ? 'is-ok'
                                                            : 'is-failed')
                                                    }
                                                >
                                                    <span
                                                        className="network-attempt-index"
                                                        aria-hidden="true"
                                                    >
                                                        {index + 1}
                                                    </span>
                                                    <div className="network-attempt-info">
                                                        <strong>
                                                            {attempt.engine === 'model'
                                                                ? `模型搜索${attempt.model ? ' · ' + attempt.model : ''}`
                                                                : `${attempt.engine === 'bing' ? 'Bing' : '百度'} · ${attempt.mode === 'direct' ? '直接读取' : '浏览器加载'}`}
                                                        </strong>
                                                        <p>
                                                            {attempt.status === 'ok'
                                                                ? attempt.engine === 'model'
                                                                    ? '已取得联网回答'
                                                                    : `有效结果 ${attempt.count ?? 0} 条`
                                                                : attempt.reason ||
                                                                  '未取得有效结果'}
                                                        </p>
                                                    </div>
                                                    <span className="network-attempt-time">
                                                        {attempt.status === 'ok' ? (
                                                            <Check size={14} />
                                                        ) : (
                                                            <CircleAlert size={14} />
                                                        )}
                                                        <span>
                                                            {(
                                                                (attempt.elapsedMs || 0) / 1000
                                                            ).toFixed(1)}{' '}
                                                            秒
                                                        </span>
                                                    </span>
                                                </li>
                                            ))}
                                        </ol>
                                    </Disclosure>
                                )}
                            </div>
                        </div>
                    )}
                </Collapse>
            </section>
        </div>
    );
}
