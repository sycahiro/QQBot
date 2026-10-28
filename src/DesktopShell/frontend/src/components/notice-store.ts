export interface NoticeEntry {
    id: number;
    message: string;
    error: boolean;
    title?: string;
    onClose: () => void;
}
let sequence = 0;
let entries: NoticeEntry[] = [];
const listeners = new Set<() => void>();
const serverEntries: NoticeEntry[] = [];
export function subscribeNotices(listener: () => void) {
    listeners.add(listener);
    return () => {
        listeners.delete(listener);
    };
}
export const getNotices = () => entries;
export const getServerNotices = () => serverEntries;
function publish() {
    for (const listener of listeners) listener();
}
export function addNotice(value: Omit<NoticeEntry, 'id'>) {
    const entry = { ...value, id: ++sequence };
    const overflow = entries.slice(3);
    entries = [entry, ...entries.slice(0, 3)];
    publish();
    for (const old of overflow) old.onClose();
    return entry.id;
}
export function dismissNotice(id: number) {
    const entry = entries.find((item) => item.id === id);
    if (!entry) return;
    entries = entries.filter((item) => item.id !== id);
    publish();
    entry.onClose();
}
