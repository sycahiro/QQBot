import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { Terminal } from 'lucide-react';
import { scrollToY } from './motion';

export function Logs({ ready }: { ready: boolean }) {
    const cancelScroll = useRef<(() => void) | null>(null);
    useEffect(() => () => cancelScroll.current?.(), []);
    const [lines, setLines] = useState<{ id: string; text: string }[]>([]);
    const [error, setError] = useState('');
    const [search, setSearch] = useState('');
    const [paused, setPaused] = useState(false);
    const viewport = useRef<HTMLDivElement>(null),
        following = useRef(true);
    const anchor = useRef<{ id: string; offset: number } | null>(null);
    const searchOrigin = useRef<{ id: string; offset: number } | null>(null);
    const searchQuery = useRef('');
    const rememberPosition = () => {
        const element = viewport.current;
        if (!element || following.current) return;
        const top = element.getBoundingClientRect().top;
        const row = Array.from(element.querySelectorAll<HTMLElement>('[data-log-id]')).find(
            (item) => item.getBoundingClientRect().bottom > top,
        );
        if (row)
            anchor.current = {
                id: row.dataset.logId!,
                offset: row.getBoundingClientRect().top - top,
            };
    };
    const [atLatest, setAtLatest] = useState(true);
    useLayoutEffect(() => {
        const element = viewport.current;
        if (element && following.current) element.scrollTop = element.scrollHeight;
        else if (element && anchor.current) {
            const saved = anchor.current;
            const line = Array.from(element.querySelectorAll('pre')).find(
                (row) => row.dataset.logId === saved.id,
            );
            if (line)
                element.scrollTop +=
                    line.getBoundingClientRect().top -
                    element.getBoundingClientRect().top -
                    saved.offset;
        }
        anchor.current = null;
    }, [lines, search]);
    useEffect(() => {
        if (!ready || paused) return;
        let active = true;
        let timer: number;
        const read = async () => {
            if (!active) return;
            if (!document.hidden) {
                try {
                    const result = await window.pywebview!.api.get_logs();
                    if (active && result.ok) {
                        rememberPosition();
                        setLines(result.entries);
                        setError('');
                    } else if (active && !result.ok) setError(result.error.message);
                } catch {
                    if (active) setError('运行日志读取失败');
                }
            }
            if (active) timer = window.setTimeout(read, 2000);
        };
        void read();
        return () => {
            active = false;
            clearTimeout(timer);
        };
    }, [ready, paused]);
    const visible = lines.filter((line) =>
        line.text.toLocaleLowerCase().includes(search.toLocaleLowerCase()),
    );
    return (
        <section className="ui-card console-panel">
            <div className="console-panel-heading">
                <div>
                    <h2>运行日志</h2>
                    <p>本次启动的最近 200 行记录。</p>
                </div>
                <Terminal size={18} />
            </div>
            <div className="logs-toolbar">
                <input
                    value={search}
                    placeholder="搜索消息、模块或级别…"
                    aria-label="搜索日志"
                    onChange={(e) => {
                        cancelScroll.current?.();
                        const next = e.target.value;
                        if (!searchQuery.current && next) {
                            rememberPosition();
                            searchOrigin.current = anchor.current;
                        } else if (searchQuery.current && !next) {
                            anchor.current = searchOrigin.current;
                            searchOrigin.current = null;
                        } else rememberPosition();
                        searchQuery.current = next;
                        setSearch(next);
                    }}
                />
                <button className="btn" onClick={() => setPaused((value) => !value)}>
                    {paused ? '恢复刷新' : '暂停刷新'}
                </button>
                <button
                    className="btn"
                    disabled={atLatest}
                    onClick={() => {
                        following.current = true;
                        setAtLatest(true);
                        const element = viewport.current;
                        if (element) {
                            cancelScroll.current?.();
                            cancelScroll.current = scrollToY(element, element.scrollHeight);
                        }
                    }}
                >
                    回到最新
                </button>
            </div>
            {error && <p className="desktop-error">{error}</p>}
            <div
                className="log-lines"
                ref={viewport}
                tabIndex={0}
                aria-label="运行日志内容"
                onScroll={(e) => {
                    // Filtering may clamp the viewport to zero and fire scroll;
                    // that is not a user's request to resume following the tail.
                    if (searchQuery.current) return;
                    const element = e.currentTarget;
                    const bottom =
                        element.scrollHeight - element.scrollTop - element.clientHeight < 40;
                    following.current = bottom;
                    setAtLatest(bottom);
                }}
            >
                {visible.length ? (
                    visible.map((line) => (
                        <pre
                            key={line.id}
                            data-log-id={line.id}
                            className={
                                / ERROR | CRITICAL /.test(line.text)
                                    ? 'log-error'
                                    : / WARNING /.test(line.text)
                                      ? 'log-warning'
                                      : ''
                            }
                        >
                            {line.text}
                        </pre>
                    ))
                ) : (
                    <p className="action-notice">
                        {search
                            ? '没有匹配的日志'
                            : '暂无运行日志；模型的处理详情在 QQ Bot 页的会话中查看。'}
                    </p>
                )}
            </div>
        </section>
    );
}
