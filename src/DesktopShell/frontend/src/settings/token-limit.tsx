import type { BotConfig } from '../business';
import { Select } from '../components/select';

/** Explicit wire choice: compatible Chat services support different limit names. */
export function TokenLimit({
    api,
    onChange,
}: {
    api: BotConfig['api'];
    onChange: (field: keyof BotConfig['api'], value: string | number) => void;
}) {
    return (
        <>
            <label>
                输出 Token 上限
                <input
                    type="number"
                    min={1}
                    max={65536}
                    value={api.maxOutputTokens}
                    onChange={(e) => onChange('maxOutputTokens', Number(e.target.value))}
                />
                <small>限制单次模型输出，包含服务商计入的思考内容。</small>
            </label>
            {api.protocol === 'chat' && (
                <label>
                    Chat 上限参数
                    <Select
                        label="Chat 上限参数"
                        value={api.chatTokenLimitField}
                        options={[
                            { value: 'max_tokens', label: '通用兼容 · max_tokens' },
                            {
                                value: 'max_completion_tokens',
                                label: '新版 Chat · max_completion_tokens',
                            },
                        ]}
                        onChange={(value) => onChange('chatTokenLimitField', value)}
                    />
                    <small>按服务商说明选择，不会在失败后自动换用参数重试。</small>
                </label>
            )}
        </>
    );
}
