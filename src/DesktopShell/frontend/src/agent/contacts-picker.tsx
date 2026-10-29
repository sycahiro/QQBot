import { useEffect, useRef, useState } from 'react';
import { Users, RefreshCw } from 'lucide-react';
import type { Contact } from '../desktop';
import type { SettingsEditor } from './settings-editor';
import { Disclosure } from '../components/disclosure';

export function ContactPicker({ editor }: { editor: SettingsEditor }) {
    const [contacts, setContacts] = useState<{ groups: Contact[]; private: Contact[] } | null>(
        null,
    );
    const [query, setQuery] = useState(''),
        [busy, setBusy] = useState(false),
        [error, setError] = useState('');
    const alive = useRef(true);
    useEffect(() => {
        alive.current = true;
        return () => {
            alive.current = false;
        };
    }, []);
    const load = async () => {
        if (busy) return;
        setBusy(true);
        setError('');
        try {
            const result = await window.pywebview!.api.get_contacts(editor.account);
            if (!alive.current) return;
            if (result.ok && result.account === editor.account) setContacts(result);
            else setError(result.ok ? '连接账号已变化，请重新打开设置' : result.error.message);
        } catch {
            if (alive.current) setError('联系人读取失败，请手动刷新');
        } finally {
            if (alive.current) setBusy(false);
        }
    };
    const toggle = (kind: 'groups' | 'private', id: string, checked: boolean) => {
        const draft = editor.getSnapshot().draft;
        const values = new Set(draft.lists[kind].split(/[\s,，;；]+/).filter(Boolean));
        if (checked) values.add(id);
        else values.delete(id);
        editor.change({ ...draft, lists: { ...draft.lists, [kind]: [...values].join('\n') } });
    };
    const draft = editor.getSnapshot().draft;
    return (
        <div className="form-wide">
            <Disclosure
                title={
                    <>
                        <Users size={15} />
                        从联系人勾选白名单
                    </>
                }
            >
                <div className="contact-picker-toolbar">
                    <input
                        aria-label="搜索联系人"
                        placeholder="搜索群名、好友备注或号码"
                        value={query}
                        onChange={(e) => setQuery(e.target.value)}
                    />
                    <button
                        type="button"
                        className="btn"
                        disabled={busy}
                        onClick={() => void load()}
                    >
                        <RefreshCw size={14} />
                        {busy ? '读取中…' : contacts ? '刷新联系人' : '读取联系人'}
                    </button>
                </div>
                {error && (
                    <p className="desktop-error" role="alert">
                        {error}
                    </p>
                )}
                {contacts && (
                    <div className="contact-picker-grid">
                        {(['groups', 'private'] as const).map((kind) => {
                            const selected = new Set(
                                draft.lists[kind].split(/[\s,，;；]+/).filter(Boolean),
                            );
                            const matches = contacts[kind].filter((c) =>
                                `${c.name} ${c.id}`
                                    .toLowerCase()
                                    .includes(query.trim().toLowerCase()),
                            );
                            return (
                                <div key={kind}>
                                    <h3>
                                        {kind === 'groups' ? '群聊' : '好友'} · 已选 {selected.size}
                                    </h3>
                                    <div className="contact-picker-list">
                                        {matches.slice(0, 200).map((c) => (
                                            <label className="contact-picker-item" key={c.id}>
                                                <input
                                                    type="checkbox"
                                                    checked={selected.has(c.id)}
                                                    onChange={(e) =>
                                                        toggle(kind, c.id, e.target.checked)
                                                    }
                                                />
                                                <span>
                                                    <strong>{c.name}</strong>
                                                    <small>{c.id}</small>
                                                </span>
                                            </label>
                                        ))}
                                        {!matches.length && (
                                            <p className="action-notice">没有匹配联系人</p>
                                        )}
                                    </div>
                                    {matches.length > 200 && (
                                        <small>匹配 {matches.length} 项，请缩小搜索范围。</small>
                                    )}
                                </div>
                            );
                        })}
                    </div>
                )}
                <p className="action-notice">勾选要接入的群聊和好友。</p>
            </Disclosure>
        </div>
    );
}
