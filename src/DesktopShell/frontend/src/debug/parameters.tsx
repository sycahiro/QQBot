import type { Contact, DebugAction } from '../desktop';
import { Select } from '../components/select';

type Schema = {
    type?: string | string[];
    description?: string;
    enum?: unknown[];
    default?: unknown;
};
export function DebugParameters({
    doc,
    value,
    onChange,
    contacts,
}: {
    doc?: DebugAction;
    value: string;
    onChange: (s: string) => void;
    contacts: { groups: Contact[]; private: Contact[] };
}) {
    let params: Record<string, unknown>;
    try {
        params = JSON.parse(value);
        if (!params || Array.isArray(params) || typeof params !== 'object') throw Error();
    } catch {
        return <p className="action-notice">请先修正下方的 JSON 参数，再使用表单。</p>;
    }
    const schema = doc?.inputSchema as
        { properties?: Record<string, Schema>; required?: string[] } | undefined;
    const properties: Record<string, Schema> =
        schema?.properties ||
        Object.fromEntries(
            (doc?.params || []).map((p) => [
                p.name,
                { type: 'string', description: p.description },
            ]),
        );
    const change = (key: string, next: unknown) => {
        const copy = { ...params };
        if (next === undefined) delete copy[key];
        else copy[key] = next;
        onChange(JSON.stringify(copy, null, 2));
    };
    return (
        <div className="bot-form-grid">
            {!Object.keys(properties).length && <p className="action-notice">此接口无需参数。</p>}
            {Object.entries(properties).map(([name, s]) => {
                const required = schema?.required?.includes(name),
                    label = `${name}${required ? ' *' : ''}`;
                const current = params[name];
                const options =
                    name === 'group_id'
                        ? contacts.groups
                        : name === 'user_id'
                          ? contacts.private
                          : [];
                if (name === 'group_id' || name === 'user_id' || name === 'chat_key')
                    return (
                        <div className="bot-field" key={name}>
                            <span>{label}</span>
                            <Select
                                editable
                                label={label}
                                value={String(current ?? '')}
                                placeholder="输入号码，或读取联系人后选择"
                                options={
                                    name === 'chat_key'
                                        ? [
                                              ...contacts.groups.map((c) => ({
                                                  value: `group:${c.id}`,
                                                  label: `群聊 · ${c.name} · ${c.id}`,
                                              })),
                                              ...contacts.private.map((c) => ({
                                                  value: `private:${c.id}`,
                                                  label: `私聊 · ${c.name} · ${c.id}`,
                                              })),
                                          ]
                                        : options.map((c) => ({
                                              value: c.id,
                                              label: `${c.name} · ${c.id}`,
                                          }))
                                }
                                onChange={(v) => change(name, v || undefined)}
                            />
                            {s.description && <small>{s.description}</small>}
                        </div>
                    );
                if (s.type === 'boolean')
                    return (
                        <div className="bot-field" key={name}>
                            <span>{label}</span>
                            <Select
                                label={label}
                                value={current === undefined ? '' : String(current)}
                                options={[
                                    { value: '', label: '使用接口默认值' },
                                    { value: 'true', label: '是' },
                                    { value: 'false', label: '否' },
                                ]}
                                onChange={(v) => change(name, v === '' ? undefined : v === 'true')}
                            />
                        </div>
                    );
                if (s.enum)
                    return (
                        <div className="bot-field" key={name}>
                            <span>{label}</span>
                            <Select
                                label={label}
                                value={String(current ?? '')}
                                options={s.enum.map((v) => ({
                                    value: String(v),
                                    label: String(v),
                                }))}
                                onChange={(v) => change(name, v)}
                            />
                        </div>
                    );
                if (name === 'message')
                    return (
                        <label className="form-wide" key={name}>
                            {label}
                            <textarea
                                rows={3}
                                value={
                                    typeof current === 'string'
                                        ? current
                                        : JSON.stringify(current ?? '')
                                }
                                onChange={(e) => change(name, e.target.value)}
                            />
                            <small>复杂消息可使用“消息构建”，或编辑原始 JSON。</small>
                        </label>
                    );
                return (
                    <label key={name}>
                        {label}
                        <input
                            type={s.type === 'integer' || s.type === 'number' ? 'number' : 'text'}
                            value={String(current ?? '')}
                            onChange={(e) =>
                                change(
                                    name,
                                    e.target.value === ''
                                        ? undefined
                                        : s.type === 'integer' || s.type === 'number'
                                          ? Number(e.target.value)
                                          : e.target.value,
                                )
                            }
                        />
                        {s.description && <small>{s.description}</small>}
                    </label>
                );
            })}
        </div>
    );
}
