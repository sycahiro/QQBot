import { storageBytes } from './settings/storage-types';
import { Cpu } from 'lucide-react';
import { useResources } from './desktop';

function Usage({ label, value, detail }: { label: string; value: number | null; detail: string }) {
    return (
        <div>
            <div className="resource-label">
                <small>{label}</small>
                <strong>{value == null ? '采样中' : `${value.toFixed(1)}%`}</strong>
            </div>
            <div
                className="resource-meter"
                role="meter"
                aria-label={label}
                aria-valuemin={0}
                aria-valuemax={100}
                aria-valuenow={value ?? undefined}
            >
                <span
                    style={{ width: `${value == null ? 0 : Math.max(0, Math.min(100, value))}%` }}
                />
            </div>
            <p>{detail}</p>
        </div>
    );
}

export function Resources({ ready }: { ready: boolean }) {
    const { resources: data, resourceError } = useResources(ready);
    return (
        <section className="ui-card console-panel">
            <div className="console-panel-heading">
                <div>
                    <h2>运行环境</h2>
                    <p>查看本机资源占用。</p>
                </div>
                <Cpu size={18} />
            </div>
            <div className="environment-grid">
                <div>
                    <strong>{data?.hostname ?? '正在读取主机信息'}</strong>
                    <p>{data?.cpuModel ?? '—'}</p>
                </div>
                <Usage
                    label="CPU 使用率"
                    value={data?.cpuPercent ?? null}
                    detail={data ? `${data.logicalCores} 个逻辑处理器` : '—'}
                />
                <Usage
                    label="内存使用率"
                    value={data?.memoryPercent ?? null}
                    detail={
                        data
                            ? `${storageBytes(data.memoryUsed)} / ${storageBytes(data.memoryTotal)}`
                            : '—'
                    }
                />
                <div className="resource-app">
                    <small>应用内存</small>
                    <strong>{data ? storageBytes(data.appMemory) : '—'}</strong>
                    <p>QQBot 及其子进程</p>
                </div>
            </div>
            {resourceError && (
                <p className="resource-error" role="status">
                    {resourceError}
                </p>
            )}
        </section>
    );
}
