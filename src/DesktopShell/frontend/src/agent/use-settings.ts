import { useEffect, useState, useSyncExternalStore } from 'react';
import { SettingsEditor } from './settings-editor';
import type { ConfigurationResult } from '../desktop';
import type { BotConfig, ApiResult } from '../business';

let cached: SettingsEditor | null = null;
let globalCached: SettingsEditor | null = null;
const emptySubscribe = () => () => {};
const emptySnapshot = () => null;

export function resetSettingsEditor() {
    cached?.dispose();
    cached = null;
}

export function useSettings(
    ready: boolean,
    expectedAccount?: string,
    scope: 'bot' | 'global' = 'bot',
) {
    const [editor, setEditor] = useState<SettingsEditor | null>(null);
    const [error, setError] = useState('');
    useEffect(() => {
        if (!ready) return;
        let active = true;
        let current = scope === 'global' ? globalCached : cached;
        const cache = (value: SettingsEditor | null) => {
            if (scope === 'global') globalCached = value;
            else cached = value;
        };
        const observed = current?.getSnapshot();
        const normalize = (
            result: ConfigurationResult<{ config: BotConfig }>,
        ): ApiResult<{ account: string; config: BotConfig }> =>
            result.ok
                ? (
                      scope === 'global'
                          ? result.scope === 'global'
                          : typeof result.account === 'string'
                  )
                    ? { ...result, account: scope === 'global' ? 'global' : result.account! }
                    : {
                          ok: false,
                          error: {
                              code: 'SCOPE_CHANGED',
                              message: '配置范围已变化，请重新打开设置',
                          },
                      }
                : result;
        const request =
            scope === 'global'
                ? window.pywebview!.api.get_global_settings().then(normalize)
                : window.pywebview!.api.get_bot_settings(expectedAccount);
        void request
            .then((result) => {
                if (!active) return;
                if (!result.ok) {
                    setError(result.error.message);
                    return;
                }
                if (scope === 'bot' && expectedAccount && result.account !== expectedAccount) {
                    resetSettingsEditor();
                    setEditor(null);
                    setError('连接账号已变化，请重新打开机器人设置');
                    return;
                }
                if (!result.account || !result.config) {
                    current?.dispose();
                    cache(null);
                    setEditor(null);
                    setError('');
                    return;
                }
                if (current?.account !== result.account) {
                    current?.dispose();
                    current = new SettingsEditor(
                        result.account,
                        result.config,
                        (patch, account) =>
                            scope === 'global'
                                ? window.pywebview!.api.save_global_settings(patch).then(normalize)
                                : window.pywebview!.api.save_bot_settings(patch, account),
                        (operation, data, account) =>
                            window
                                .pywebview!.api.manage_model_profile(
                                    operation,
                                    data,
                                    scope === 'global' ? null : account,
                                )
                                .then(normalize),
                    );
                    cache(current);
                } else if (current.getSnapshot() === observed)
                    current.reconcile(
                        result.config,
                        scope === 'global' ? ['model', 'search', 'defaultPersona'] : undefined,
                    );
                setEditor(current);
                setError('');
            })
            .catch(() => {
                if (active) setError('机器人设置读取失败');
            });
        return () => {
            active = false;
        };
    }, [ready, expectedAccount, scope]);
    const state = useSyncExternalStore(
        editor?.subscribe ?? emptySubscribe,
        editor?.getSnapshot ?? emptySnapshot,
        emptySnapshot,
    );
    return { editor, state, error };
}
