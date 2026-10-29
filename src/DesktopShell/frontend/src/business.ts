export type ApiResult<T> =
    ({ ok: true } & T) | { ok: false; error: { code: string; message: string } };
export interface ChatSummary {
    chatKey: string;
    name: string;
    count: number;
    lastText: string;
    lastSenderName: string;
    lastTs: number;
    lastId: number;
    unread: number;
}
export interface ArchivedMessage {
    id: number;
    mid: string | null;
    ts: number;
    senderId: string;
    senderName: string;
    text: string;
    self: boolean;
    withdrawn: boolean;
    read: boolean;
    hasImage?: boolean;
    hasForward?: boolean;
}
export interface Sticker {
    id: string;
    note: string;
    tags: string[];
    usage: string;
    width: number;
    height: number;
    bytes: number;
    firstFrame: boolean;
    created: number;
    uses: number;
}
export interface BotConfig {
    mediaOptions: {
        vision: boolean;
        sendImages: boolean;
        imageProfileId: string;
    };
    webSearch: {
        enabled: boolean;
        maxResults: number;
        browse: boolean;
        fallbackEnabled: boolean;
        fallbackProfileId: string;
    };
    sticker: { enabled: boolean; collectEnabled: boolean; allowPoke: boolean };
    api: {
        protocol: 'chat' | 'responses' | 'anthropic';
        sendTemperature: boolean;
        maxOutputTokens: number;
        chatTokenLimitField: 'max_tokens' | 'max_completion_tokens';
        baseUrl: string;
        model: string;
        apiKeyConfigured: boolean;
        temperature: number;
        maxRounds: number;
        timeoutMs: number;
        vision: boolean;
        visionModel: string;
        sendImages: boolean;
    };
    persona: { roleText: string; customRules: string };
    defaultPersona: { roleText: string; customRules: string };
    allow: { groups: string[]; private: string[] };
    deny: { groups: string[]; private: string[] };
    blockedUsers: string[];
    ownerQQ: string;
    groupTrigger: 'at' | 'keywords' | 'random' | 'all';
    groupKeywords: string[];
    groupRandomPercent: number;
    contextLimit: number;
    profiles: { id: string; name: string; api: BotConfig['api'] }[];
    activeProfileId: string;
}
export interface AgentStatus {
    enabled: boolean;
    account: string | null;
    running: number;
    queued: number;
    active: number;
    manual?: number;
    error: string | null;
    notice?: string | null;
    model?: string;
}
export interface Usage {
    promptTokens: number;
    completionTokens: number;
    totalTokens: number;
    calls: number;
    todayTokens?: number;
    sessions?: number;
}
export interface Session {
    id: string;
    account: string;
    chatKey: string;
    name: string;
    started: number;
    ended: number | null;
    status: 'running' | 'done' | 'noreply' | 'error' | 'aborted';
    model: string;
    triggerText: string;
    usage: Usage;
    sent: {
        text: string;
        messageId: string | null;
        ts: number;
        verified?: boolean;
        type?: 'text' | 'image' | 'poke';
    }[];
    reason: string;
    records?: SessionRecord[];
}
export type SessionRecord = {
    kind: string;
    status?: 'running' | 'done' | 'error' | 'aborted';
    started?: number;
    ended?: number | null;
    stage?: 'chat' | 'media';
    model?: string;
    protocol?: string;
    text?: string;
    title?: string;
    mode?: string;
    retryOf?: string | null;
    messages?: { role: string; content: string }[];
    name?: string;
    args?: Record<string, unknown>;
    result?: Record<string, unknown>;
    isError?: boolean;
};
export interface MemoryChat {
    chatKey: string;
    name: string;
    count: number;
    members: number;
}
export interface MemoryMember {
    userId: string;
    target: string;
    entries: { id: number; content: string; ts: number }[];
}
export interface MemoryPreview {
    token: string;
    userId: string;
    before: string[];
    after: string[];
    model: string;
    tokens: number;
    sourceCount: number;
    expiresIn: number;
}
export interface MarketEntry {
    id: string;
    name: string;
    description: string;
    version: string;
    author: string;
    category: string;
}
export function chatLabel(chat: Pick<ChatSummary, 'chatKey' | 'name'>) {
    const [kind, id] = chat.chatKey.split(':');
    return {
        title: `${kind === 'group' ? '群聊' : '私聊'} · ${chat.name || '未识别名称'}`,
        number: `${kind === 'group' ? '群号' : '用户编号'}：${id}`,
    };
}
