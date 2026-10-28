import { uiTransition } from '../motion';
import { useEffect, useRef, useState } from 'react';
import { AnimatePresence, motion, useReducedMotion } from 'motion/react';
import { ArrowLeft, ExternalLink, Package, RefreshCw } from 'lucide-react';
import type { MarketEntry } from '../business';
import { AnimatedList } from '../components/animated-list';
import { useTabNavigation } from '../components/tab-navigation';

export function Market({ ready, onBack }: { ready: boolean; onBack: () => void }) {
    const {
        tab: kind,
        setTab: setKind,
        panel,
        minHeight,
        onExitComplete,
    } = useTabNavigation<'plugin' | 'skill'>('plugin');
    const [data, setData] = useState<{ kind: string; items: MarketEntry[] }>({
        kind: '',
        items: [],
    });
    const [search, setSearch] = useState(''),
        [error, setError] = useState(''),
        [busy, setBusy] = useState(false);
    const [revision, refresh] = useState(0),
        [limit, setLimit] = useState(30);
    const cache = useRef(new Map<string, MarketEntry[]>()),
        reduced = useReducedMotion();
    useEffect(() => setLimit(30), [kind, search]);
    useEffect(() => {
        if (!ready) return;
        let active = true;
        setBusy(true);
        setError('');
        setData({ kind, items: cache.current.get(kind) ?? [] });
        void window
            .pywebview!.api.get_market(kind)
            .then((result) => {
                if (!active) return;
                if (result.ok) {
                    cache.current.set(kind, result.items);
                    setData({ kind, items: result.items });
                } else setError(result.error.message);
            })
            .catch(() => {
                if (active) setError('市场目录读取失败，请刷新重试');
            })
            .finally(() => {
                if (active) setBusy(false);
            });
        return () => {
            active = false;
        };
    }, [ready, kind, revision]);
    // 官方市场只有列表页，界面上的跳转一律交给系统浏览器打开对应类型的页面。
    const openStore = async () => {
        setError('');
        try {
            const result = await window.pywebview!.api.open_market_page(kind);
            if (!result.ok) setError(result.error.message);
        } catch {
            setError('打开官方市场页面失败，请手动访问 www.kondius.cn');
        }
    };
    const items = data.kind === kind ? data.items : (cache.current.get(kind) ?? []);
    const visible = items.filter((item) =>
        `${item.name} ${item.description} ${item.author}`
            .toLocaleLowerCase()
            .includes(search.toLocaleLowerCase()),
    );
    const phase =
        busy && !items.length
            ? 'loading'
            : error && !items.length
              ? 'error'
              : visible.length
                ? 'results'
                : 'empty';
    return (
        <div className="desktop-sections">
            <div className="archive-toolbar">
                <div>
                    <button className="qq-refresh" onClick={onBack}>
                        <ArrowLeft size={14} />
                        返回扩展
                    </button>
                    <button
                        className="qq-refresh"
                        disabled={busy}
                        onClick={() => refresh((value) => value + 1)}
                    >
                        <RefreshCw size={14} className={busy ? 'market-refreshing' : undefined} />
                        刷新目录
                    </button>
                    <button className="qq-refresh" onClick={() => void openStore()}>
                        <ExternalLink size={14} />
                        原项目市场
                    </button>
                </div>
                <p>原项目公开目录，仅供浏览。</p>
            </div>
            <div className="logs-toolbar">
                <nav className="agent-tabs" aria-label="市场类型">
                    {(['plugin', 'skill'] as const).map((value) => (
                        <button
                            key={value}
                            aria-current={kind === value ? 'page' : undefined}
                            onClick={() => setKind(value)}
                        >
                            {kind === value && (
                                <motion.span
                                    className="agent-tab-highlight"
                                    layoutId="market-kind"
                                    transition={uiTransition(reduced)}
                                />
                            )}
                            {value === 'plugin' ? 'Plugins' : 'Skills'}
                        </button>
                    ))}
                </nav>
                <input
                    aria-label="搜索市场"
                    placeholder="搜索名称、说明或作者"
                    value={search}
                    onChange={(event) => setSearch(event.target.value)}
                />
            </div>
            <div ref={panel} style={{ minHeight }} className="tab-panel-frame" aria-busy={busy}>
                <AnimatePresence mode="wait" initial={false} onExitComplete={onExitComplete}>
                    <motion.div
                        key={kind}
                        className="desktop-sections"
                        initial={{ opacity: 0, x: reduced ? 0 : 16 }}
                        animate={{ opacity: 1, x: 0 }}
                        exit={{ opacity: 0, x: reduced ? 0 : -10, pointerEvents: 'none' }}
                        transition={uiTransition(reduced)}
                    >
                        {error && items.length > 0 && (
                            <p className="desktop-error" role="alert">
                                {error}
                            </p>
                        )}
                        <AnimatePresence mode="wait" initial={false}>
                            <motion.div
                                key={phase}
                                initial={{ opacity: 0, y: reduced ? 0 : 6 }}
                                animate={{ opacity: 1, y: 0 }}
                                exit={{ opacity: 0 }}
                                transition={uiTransition(reduced)}
                            >
                                {phase === 'results' ? (
                                    <AnimatedList className="market-grid" staged>
                                        {visible.slice(0, limit).map((item) => (
                                            <section
                                                className="ui-card console-panel"
                                                key={item.id}
                                            >
                                                <div className="console-panel-heading">
                                                    <div>
                                                        <h2>{item.name || item.id}</h2>
                                                        <p>
                                                            {item.author || '作者未注明'}
                                                            {item.version
                                                                ? ` · v${item.version}`
                                                                : ''}
                                                        </p>
                                                    </div>
                                                    <Package size={18} />
                                                </div>
                                                <p className="market-description">
                                                    {item.description || '暂无说明'}
                                                </p>
                                                <span className="session-status">仅供浏览</span>
                                            </section>
                                        ))}
                                    </AnimatedList>
                                ) : (
                                    <p
                                        className={
                                            phase === 'error' ? 'desktop-error' : 'action-notice'
                                        }
                                        role={phase === 'error' ? 'alert' : 'status'}
                                    >
                                        {phase === 'loading'
                                            ? '正在读取市场目录…'
                                            : phase === 'error'
                                              ? error
                                              : search
                                                ? '没有匹配的条目'
                                                : '市场暂时没有条目'}
                                    </p>
                                )}
                            </motion.div>
                        </AnimatePresence>
                        {!busy && visible.length > limit && (
                            <button
                                className="qq-refresh"
                                onClick={() => setLimit((value) => value + 30)}
                            >
                                加载更多（共 {visible.length} 项）
                            </button>
                        )}
                    </motion.div>
                </AnimatePresence>
            </div>
        </div>
    );
}
