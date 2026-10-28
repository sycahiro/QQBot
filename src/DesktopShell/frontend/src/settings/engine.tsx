import { useEffect, useRef, useState } from 'react';
import { Bot, Save } from 'lucide-react';
import type { EngineStatusCommand } from '../desktop';
import { Notice } from '../components/notice';

const DEFAULT_STATUS_COMMAND: EngineStatusCommand = {
    enabled: false,
    swallow: false,
    cooldownSeconds: 5,
    trigger: '#sl',
};

export function EngineSettings({ ready }: { ready: boolean }) {
    const [statusCommand, setStatusCommand] = useState<EngineStatusCommand>(DEFAULT_STATUS_COMMAND);
    const [historySync, setHistorySync] = useState(false);
    const [saved, setSaved] = useState('');
    const [notice, setNotice] = useState(''),
        [error, setError] = useState(''),
        [busy, setBusy] = useState(false);
    const mounted = useRef(true);
    useEffect(() => {
        mounted.current = true;
        return () => {
            mounted.current = false;
        };
    }, []);
    useEffect(() => {
        if (!ready) return;
        void window
            .pywebview!.api.get_engine_settings()
            .then((result) => {
                if (!mounted.current) return;
                if (result.ok) {
                    if (result.statusCommand) setStatusCommand(result.statusCommand);
                    setHistorySync(Boolean(result.historySync?.enabled));
                    setError('');
                } else setError(result.error.message);
            })
            .catch(() => {
                if (mounted.current) setError('引擎设置读取失败，请重试');
            });
    }, [ready]);
    const save = async () => {
        setBusy(true);
        setNotice('');
        setError('');
        setSaved('');
        try {
            const result = await window.pywebview!.api.save_engine_settings(statusCommand, {
                enabled: historySync,
            });
            if (!mounted.current) return;
            if (result.ok) {
                setStatusCommand(result.statusCommand);
                setHistorySync(result.historySync.enabled);
                setSaved('已保存。重启 SnowLuma 或重新连接账号后生效。');
            } else setError(result.error.message);
        } catch {
            if (mounted.current) setError('保存未完成，请重试');
        } finally {
            if (mounted.current) setBusy(false);
        }
    };
    return (
        <div className="desktop-sections">
            <Notice
                message={error || saved || notice}
                error={Boolean(error)}
                onClose={() => {
                    setNotice('');
                    setError('');
                    setSaved('');
                }}
            />
            <section className="ui-card console-panel">
                <div className="console-panel-heading">
                    <div>
                        <h2>#sl 状态命令</h2>
                        <p>在群里或私聊发送触发词，引擎直接回复运行状态，不经过模型。</p>
                    </div>
                    <Bot size={18} />
                </div>
                <div className="bot-form-grid">
                    <label className="form-wide form-check">
                        <input
                            type="checkbox"
                            checked={statusCommand.enabled}
                            onChange={(e) =>
                                setStatusCommand({ ...statusCommand, enabled: e.target.checked })
                            }
                        />
                        启用状态命令
                    </label>
                    <label className="form-wide form-check">
                        <input
                            type="checkbox"
                            checked={statusCommand.swallow}
                            disabled={!statusCommand.enabled}
                            onChange={(e) =>
                                setStatusCommand({ ...statusCommand, swallow: e.target.checked })
                            }
                        />
                        只回状态，不把这条消息转给机器人
                    </label>
                    <label className="form-wide">
                        触发词
                        <input
                            maxLength={32}
                            value={statusCommand.trigger}
                            disabled={!statusCommand.enabled}
                            onChange={(e) =>
                                setStatusCommand({ ...statusCommand, trigger: e.target.value })
                            }
                            placeholder="#sl"
                        />
                        <small>整条消息精确匹配（忽略大小写），1 到 32 个字符。</small>
                    </label>
                    <label className="form-wide">
                        每个会话的回复冷却（秒）
                        <input
                            type="number"
                            min={0}
                            max={3600}
                            value={statusCommand.cooldownSeconds}
                            disabled={!statusCommand.enabled}
                            onChange={(e) =>
                                setStatusCommand({
                                    ...statusCommand,
                                    cooldownSeconds: Number(e.target.value),
                                })
                            }
                        />
                        <small>0 表示不冷却；同一群或私聊在冷却期内不重复回复。</small>
                    </label>
                </div>
            </section>
            <section className="ui-card console-panel">
                <div className="console-panel-heading">
                    <div>
                        <h2>登录历史回填</h2>
                        <p>账号接入时静默拉取近一段聊天记录，供机器人更快了解上下文。</p>
                    </div>
                    <Bot size={18} />
                </div>
                <div className="bot-form-grid">
                    <label className="form-wide form-check">
                        <input
                            type="checkbox"
                            checked={historySync}
                            onChange={(e) => setHistorySync(e.target.checked)}
                        />
                        登录时回填历史消息
                    </label>
                </div>
                <div className="card-save-footer save-actions">
                    <button
                        className="qq-refresh primary-button"
                        disabled={busy || !ready}
                        onClick={() => void save()}
                    >
                        <Save size={14} />
                        保存
                    </button>
                    <small>改动保存后写入引擎配置文件（data/services/snowluma/config）。</small>
                </div>
            </section>
        </div>
    );
}
