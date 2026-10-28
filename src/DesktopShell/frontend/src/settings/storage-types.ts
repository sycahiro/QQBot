export interface StoragePolicy {
    logMaxTotalMb: number;
    logRetainDays: number;
    engineRetainDays: number;
}
export type StorageCategory = 'archives' | 'sessions' | 'memories' | 'stickers' | 'indexes';
export type StorageRequest =
    | { scope: 'logs' | 'temporary' }
    | { scope: 'account'; account: string; category: StorageCategory }
    | { scope: 'allAccounts'; category: StorageCategory; accounts: string[] };
export interface CleanupResult {
    deletedFiles: number;
    freedBytes: number;
    deletedRows: number;
    failures: string[];
}
export interface StorageAccount {
    account: string;
    databaseBytes: number;
    indexBytes: number;
    indexFiles: number;
    temporaryBytes: number;
    counts: Record<Exclude<StorageCategory, 'indexes'>, number>;
}
export interface StorageOverview {
    settings: StoragePolicy;
    busy: boolean;
    accounts: StorageAccount[];
    logs: {
        bytes: number;
        launches: number;
        activeBytes: number;
        closedLaunches: number;
        engineBytes: number;
        engineFiles: number;
        engineActiveBytes: number;
        engineClosedFiles: number;
    };
    totals: {
        logsBytes: number;
        accountBytes: number;
        temporaryBytes: number;
        serviceBytes: number;
        managedBytes: number;
    };
    lastCleanup:
        | (CleanupResult & {
              at: number;
              scope: string;
              category?: StorageCategory;
              account?: string;
          })
        | null;
}

export function storageBytes(value: number) {
    if (value < 1024) return `${value} B`;
    if (value < 1024 ** 2) return `${(value / 1024).toFixed(1)} KB`;
    if (value < 1024 ** 3) return `${(value / 1024 ** 2).toFixed(1)} MB`;
    return `${(value / 1024 ** 3).toFixed(1)} GB`;
}

export const storageCategories: { id: StorageCategory; label: string; description: string }[] = [
    { id: 'archives', label: '聊天存档', description: '保留联系人名称，清理消息和撤回标记。' },
    { id: 'sessions', label: '会话记录', description: '清理处理过程、发送回执和对应的用量统计。' },
    { id: 'memories', label: '记忆', description: '清理已保存的成员印象。' },
    { id: 'stickers', label: '表情库', description: '清理已收藏的图片、备注和标签。' },
    {
        id: 'indexes',
        label: 'QQ 消息索引',
        description: '清理通信引擎保存的消息、媒体和表情回应索引。',
    },
];
