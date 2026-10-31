import { useEffect, useRef, useState } from 'react';
import type {
    StorageOverview,
    StoragePolicy,
    StorageRequest,
    CleanupResult,
} from './settings/storage-types';
import type {
    ApiResult,
    ChatSummary,
    ArchivedMessage,
    BotConfig,
    AgentStatus,
    Session,
    Usage,
    MemoryChat,
    MemoryMember,
    MemoryPreview,
    Sticker,
} from './business';

export interface DesktopInfo {
    name: string;
    version: string;
    platform: string;
    python: string;
    renderer: string;
    snowlumaVersion?: string | null;
    uptimeSeconds: number;
    qqConnected: boolean;
    autoReply: boolean;
    module: 'desktop';
}
export interface DependencyItem {
    name: string;
    version: string;
    license: string;
    kind: 'direct' | 'development' | 'installed';
}
export interface DependencyInventory {
    pythonPackages: DependencyItem[];
    nodePackages: DependencyItem[];
    nodeVersion: string | null;
}
export type ConfigurationResult<T> = ApiResult<T & { account?: string; scope?: 'global' }>;

export interface DesktopOptions {
    trayEnabled: boolean;
    startup: boolean;
    trayReady: boolean;
}
export interface Contact {
    id: string;
    name: string;
}

interface ResourceInfo {
    hostname: string;
    cpuModel: string;
    logicalCores: number;
    cpuPercent: number | null;
    memoryTotal: number;
    memoryUsed: number;
    memoryPercent: number;
    appMemory: number;
}

export interface QqProcess {
    pid: number;
    processKey: string | null;
    version: string | null;
    account: { uin: string; nickname: string } | null;
    accountAmbiguous: boolean;
    identityReady: boolean;
}

export type QqDiscoveryResult =
    | {
          ok: true;
          processes: QqProcess[];
          selectedUin: string | null;
          warning?: string;
      }
    | { ok: false; error: { code: string; message: string } };

export interface QqConnectionInfo {
    state: 'idle' | 'connecting' | 'ready' | 'disconnecting' | 'disconnected' | 'error' | 'closed';
    connected: boolean;
    account: {
        uin: string;
        pid: number;
        nickname: string;
        version: string | null;
    } | null;
    error: string | null;
}
interface AgentConnectionInfo {
    source: 'qq';
    connection: QqConnectionInfo;
}

type DesktopAgentStatus = AgentStatus & { workspace?: AgentConnectionInfo };

type QqConnectionResult =
    | { ok: true; connection: QqConnectionInfo }
    | { ok: false; error: { code: string; message: string } };

declare global {
    interface Window {
        __QQBOT_THEME__?: 'light' | 'dark' | 'system';
        __qqbotRequestClose?: () => boolean;
        pywebview?: {
            api: {
                window_control(action: string): Promise<ApiResult<{ maximized: boolean }>>;
                resolve_window_close(
                    action: 'cancel' | 'hide' | 'exit',
                ): Promise<ApiResult<{ action: string }>>;
                save_theme(
                    theme: 'light' | 'dark' | 'system',
                ): Promise<ApiResult<{ theme: 'light' | 'dark' | 'system' }>>;
                get_bootstrap(): Promise<DesktopInfo>;
                get_resources(): Promise<ResourceInfo>;
                get_storage(): Promise<ApiResult<StorageOverview>>;
                save_storage_settings(
                    settings: StoragePolicy,
                ): Promise<ApiResult<{ overview: StorageOverview; cleanup: CleanupResult }>>;
                cleanup_storage(request: StorageRequest): Promise<
                    ApiResult<{
                        success: boolean;
                        overview: StorageOverview;
                        cleanup: CleanupResult;
                    }>
                >;
                get_desktop_options(): Promise<ApiResult<{ options: DesktopOptions }>>;
                save_desktop_options(
                    options: Omit<DesktopOptions, 'trayReady'>,
                ): Promise<ApiResult<{ options: DesktopOptions }>>;
                get_contacts(
                    account: string,
                ): Promise<ApiResult<{ account: string; groups: Contact[]; private: Contact[] }>>;
                process_archive(
                    key: string,
                    account: string,
                ): Promise<ApiResult<{ account: string; chatKey: string; accepted: boolean }>>;
                stop_session(
                    id: string,
                    account: string,
                ): Promise<ApiResult<{ account: string; stopping: boolean }>>;
                rerun_session(
                    id: string,
                    account: string,
                ): Promise<ApiResult<{ account: string; chatKey: string; accepted: boolean }>>;
                get_qq_processes(): Promise<QqDiscoveryResult>;
                get_snowluma_status(): Promise<{ stage: string; error: string | null }>;
                start_snowluma(): Promise<
                    | { ok: true; stage: string }
                    | {
                          ok: false;
                          stage?: string;
                          error: { code: string; message: string };
                      }
                >;
                stop_snowluma(): Promise<
                    | { ok: true; stage: string }
                    | {
                          ok: false;
                          stage?: string;
                          error: { code: string; message: string };
                      }
                >;
                open_snowluma_webui(): Promise<ApiResult<{ url: string; password: string | null }>>;
                get_webui_password_memo(): Promise<ApiResult<{ password: string | null }>>;
                save_webui_password_memo(
                    password: string,
                ): Promise<ApiResult<{ password: string | null }>>;
                get_qq_status(): Promise<QqConnectionInfo>;
                connect_qq_account(target: {
                    pid: number;
                    processKey: string;
                    uin: string;
                }): Promise<QqConnectionResult>;
                disconnect_qq_account(): Promise<QqConnectionResult>;
                get_archives(unreadOnly?: boolean): Promise<
                    ApiResult<{
                        account: string | null;
                        items: ChatSummary[];
                        unread: number;
                        unreadChats: number;
                        readThrough: number;
                    }>
                >;
                mark_archive_read(
                    key: string | null,
                    through: number,
                    account: string,
                ): Promise<ApiResult<{ account: string; marked: number }>>;
                get_archive_messages(
                    key: string,
                    query: string,
                    before: number | null,
                    account: string,
                ): Promise<
                    ApiResult<{
                        account: string;
                        chatKey: string;
                        items: ArchivedMessage[];
                        hasMore: boolean;
                        nextBefore: number | null;
                        query: string;
                        totalMatches: number;
                    }>
                >;
                delete_archive(
                    key: string | null,
                    account: string,
                ): Promise<ApiResult<{ account: string; deleted: number }>>;
                get_global_settings(): Promise<ApiResult<{ scope: 'global'; config: BotConfig }>>;
                save_global_settings(
                    patch: unknown,
                ): Promise<ApiResult<{ scope: 'global'; config: BotConfig }>>;
                get_bot_settings(account?: string): Promise<
                    ApiResult<{
                        account: string | null;
                        config: BotConfig | null;
                        autoReply: boolean;
                    }>
                >;
                save_bot_settings(
                    patch: unknown,
                    account: string,
                ): Promise<ApiResult<{ account: string; config: BotConfig }>>;
                manage_model_profile(
                    operation: 'save' | 'store' | 'use' | 'delete',
                    data: unknown,
                    account: string | null,
                ): Promise<ConfigurationResult<{ config: BotConfig }>>;
                get_model_list(
                    account: string | null,
                    draft?: unknown,
                    profileId?: string | null,
                ): Promise<ConfigurationResult<{ models: string[] }>>;
                test_model_connection(
                    account: string | null,
                    draft?: unknown,
                    profileId?: string | null,
                    kind?: 'text' | 'image' | 'tools',
                ): Promise<
                    ConfigurationResult<{
                        model: string;
                        reply: string;
                        latencyMs: number;
                        tokens: number;
                    }>
                >;
                test_web_search(
                    account: string | null,
                    draft: unknown,
                    probe?: { kind: 'search' | 'fetch'; value: string },
                ): Promise<ConfigurationResult<NetworkProbe>>;
                get_stickers(
                    query: string,
                    account: string,
                ): Promise<ApiResult<{ account: string; items: Sticker[]; limit: number }>>;
                get_sticker_preview(
                    id: string,
                    account: string,
                ): Promise<ApiResult<{ account: string; item: Sticker; image: string }>>;
                save_sticker(
                    id: string,
                    note: string,
                    tags: string[],
                    usage: string,
                    account: string,
                ): Promise<ApiResult<{ account: string; item: Sticker }>>;
                delete_sticker(
                    id: string | null,
                    account: string,
                ): Promise<ApiResult<{ account: string; deleted: number }>>;
                collect_sticker(
                    key: string,
                    mid: string,
                    account: string,
                ): Promise<
                    ApiResult<{
                        account: string;
                        item: Sticker & { collected: boolean; duplicate: boolean };
                    }>
                >;
                import_sticker(
                    data: string,
                    note: string,
                    tags: string[],
                    usage: string,
                    account: string,
                ): Promise<
                    ApiResult<{
                        account: string;
                        item: Sticker & { collected: boolean; duplicate: boolean };
                    }>
                >;
                expand_forward(
                    key: string,
                    mid: string,
                    account: string,
                ): Promise<
                    ApiResult<{
                        account: string;
                        messageId: string;
                        text: string;
                        cached: boolean;
                    }>
                >;
                get_agent_status(): Promise<DesktopAgentStatus>;
                set_auto_reply(
                    enabled: boolean,
                    account: string,
                ): Promise<ApiResult<{ status: AgentStatus }>>;
                get_sessions(
                    limit?: number,
                ): Promise<ApiResult<{ account: string | null; items: Session[] }>>;
                get_session(
                    id: string,
                ): Promise<ApiResult<{ account: string; session: Session | null }>>;
                delete_session(
                    id: string | null,
                    account: string,
                ): Promise<ApiResult<{ account: string; deleted: number }>>;
                get_usage(): Promise<ApiResult<{ account: string | null; usage: Usage | null }>>;
                get_memory_chats(): Promise<
                    ApiResult<{ account: string | null; items: MemoryChat[] }>
                >;
                get_memories(key: string): Promise<
                    ApiResult<{
                        account: string;
                        chatKey: string;
                        members: MemoryMember[];
                    }>
                >;
                save_memory(
                    key: string,
                    user: string,
                    target: string,
                    values: string[],
                    account: string,
                ): Promise<ApiResult<{ account: string; saved: number }>>;
                delete_memory(
                    key: string | null,
                    user: string | null,
                    account: string,
                ): Promise<ApiResult<{ account: string; deleted: number }>>;
                preview_memory(
                    key: string,
                    user: string,
                    account: string,
                ): Promise<ApiResult<{ account: string; preview: MemoryPreview }>>;
                apply_memory_preview(
                    key: string,
                    user: string,
                    token: string,
                    values: string[],
                    account: string,
                ): Promise<ApiResult<{ account: string; saved: number }>>;
                get_logs(): Promise<
                    ApiResult<{
                        lines: string[];
                        entries: { id: string; text: string }[];
                    }>
                >;
                get_diagnostics(): Promise<
                    ApiResult<{
                        account: string | null;
                        connection: QqConnectionInfo;
                        agent: AgentStatus;
                        configuration: {
                            model: string;
                            hasEndpoint: boolean;
                            hasKey: boolean;
                            allowedGroups: number;
                            allowedPrivate: number;
                        } | null;
                        usage: Usage | null;
                    }>
                >;
                get_dependencies(): Promise<ApiResult<DependencyInventory>>;
                open_project_page(
                    project: 'python' | 'node' | 'snowluma' | 'author' | 'repo' | 'issues',
                ): Promise<ApiResult<{ url: string }>>;
                mark_ready(): Promise<{ ok: boolean }>;
            };
        };
    }
}

interface NetworkAttempt {
    engine: 'bing';
    mode: 'rss';
    status: string;
    reason?: string;
    elapsedMs?: number;
    count?: number;
}
export interface NetworkProbe {
    success: boolean;
    kind: 'search' | 'fetch';
    value: string;
    elapsedMs: number;
    message?: string;
    attempts?: NetworkAttempt[];
    result?: {
        engine?: 'bing';
        mode?: 'rss';
        attempts?: NetworkAttempt[];
        results?: { title: string; url: string; snippet: string }[];
        title?: string;
        url?: string;
        content?: string;
        truncated?: boolean;
    };
    count?: number;
    title?: string;
}

export function useAgentStatus(ready: boolean) {
    const [status, setStatus] = useState<DesktopAgentStatus | null>(null);
    const revision = useRef(0);
    const selecting = useRef(false);
    useEffect(() => {
        if (!ready) return;
        let active = true;
        let timer: number;
        const refresh = async () => {
            if (!active) return;
            if (!document.hidden && !selecting.current) {
                const current = revision.current;
                try {
                    const result = await window.pywebview!.api.get_agent_status();
                    if (active && current === revision.current) setStatus(result);
                } catch {
                    if (active && current === revision.current) setStatus(null);
                }
            }
            if (active) timer = window.setTimeout(refresh, 1000);
        };
        void refresh();
        return () => {
            active = false;
            clearTimeout(timer);
        };
    }, [ready]);
    return { status, setStatus };
}

export function useQqConnection(ready: boolean) {
    const [connection, setConnection] = useState<QqConnectionInfo | null>(null);
    useEffect(() => {
        if (!ready) return;
        let active = true;
        let timer: number;
        const refresh = async () => {
            if (!active) return;
            if (!document.hidden) {
                try {
                    const status = await window.pywebview!.api.get_qq_status();
                    if (active) setConnection(status);
                } catch {
                    if (active)
                        setConnection({
                            state: 'error',
                            connected: false,
                            account: null,
                            error: 'QQ 连接状态读取失败',
                        });
                }
            }
            if (active) timer = window.setTimeout(refresh, 1000);
        };
        void refresh();
        return () => {
            active = false;
            clearTimeout(timer);
        };
    }, [ready]);
    return { connection, setConnection };
}

export function useResources(ready: boolean) {
    const [resources, setResources] = useState<ResourceInfo | null>(null);
    const [resourceError, setResourceError] = useState('');
    useEffect(() => {
        if (!ready) return;
        let active = true;
        let timer: number;
        const refresh = async () => {
            if (!active) return;
            if (!document.hidden) {
                try {
                    const data = await window.pywebview!.api.get_resources();
                    if (active) {
                        setResources(data);
                        setResourceError('');
                    }
                } catch {
                    if (active) setResourceError('资源信息暂时不可用，正在重试');
                }
            }
            if (active) timer = window.setTimeout(refresh, 2000);
        };
        void refresh();
        return () => {
            active = false;
            clearTimeout(timer);
        };
    }, [ready]);
    return { resources, resourceError };
}

export function useDesktop() {
    const [info, setInfo] = useState<DesktopInfo | null>(null);
    const [error, setError] = useState('');
    const [revision, setRevision] = useState(0);
    useEffect(() => {
        let active = true;
        let started = false;
        const connect = async () => {
            if (started || typeof window.pywebview?.api?.get_bootstrap !== 'function') return;
            started = true;
            try {
                const data = await window.pywebview.api.get_bootstrap();
                if (!data || data.module !== 'desktop' || typeof data.version !== 'string') {
                    throw new Error('窗口返回的信息不完整');
                }
                if (active) {
                    setInfo(data);
                    setError('');
                }
            } catch (reason) {
                started = false;
                if (active) setError(reason instanceof Error ? reason.message : '窗口连接失败');
            }
        };
        window.addEventListener('pywebviewready', connect);
        void connect();
        const timeout = window.setTimeout(() => {
            if (active && !started && !window.pywebview?.api)
                setError('请通过 QQBot 快捷方式打开桌面窗口');
        }, 10000);
        return () => {
            active = false;
            clearTimeout(timeout);
            window.removeEventListener('pywebviewready', connect);
        };
    }, [revision]);
    useEffect(() => {
        if (info) void window.pywebview?.api.mark_ready().catch(() => setError('窗口就绪确认失败'));
    }, [info]);
    return {
        info,
        error,
        retry: () => {
            setError('');
            setRevision((v) => v + 1);
        },
    };
}
