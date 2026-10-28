import { useEffect, useState } from 'react';
import { Activity, ArrowDownToLine, ArrowUpFromLine, Zap } from 'lucide-react';
import type { Usage as UsageData } from '../business';
import { Notice } from '../components/notice';

export function Usage({ ready }: { ready: boolean }) {
    const [usage, setUsage] = useState<UsageData | null>(null);
    const [error, setError] = useState('');
    useEffect(() => {
        if (!ready) return;
        let active = true;
        let timer: number;
        const read = async () => {
            if (!active) return;
            try {
                const result = await window.pywebview!.api.get_usage();
                if (active && result.ok) {
                    setUsage(result.usage);
                    setError('');
                } else if (active && !result.ok) setError(result.error.message);
            } catch {
                if (active) setError('用量读取失败');
            }
            if (active) timer = window.setTimeout(read, 4000);
        };
        void read();
        return () => {
            active = false;
            clearTimeout(timer);
        };
    }, [ready]);
    const cards = [
        { label: '累计 Token', value: usage?.totalTokens ?? 0, icon: Zap },
        { label: '输入 Token', value: usage?.promptTokens ?? 0, icon: ArrowUpFromLine },
        { label: '输出 Token', value: usage?.completionTokens ?? 0, icon: ArrowDownToLine },
        { label: '模型请求', value: usage?.calls ?? 0, icon: Activity },
    ];
    return (
        <div className="desktop-sections">
            <Notice title="用量读取" message={error} error onClose={() => setError('')} />
            <div className="console-metrics-grid">
                {cards.map(({ label, value, icon: Icon }) => (
                    <section className="ui-card console-metric" key={label}>
                        <div className="metric-label">
                            {label}
                            <Icon size={18} />
                        </div>
                        <strong className="metric-value">{value.toLocaleString()}</strong>
                    </section>
                ))}
            </div>
            <p className="action-notice">按当前账号保留的会话记录统计，费用以服务商账单为准。</p>
        </div>
    );
}
