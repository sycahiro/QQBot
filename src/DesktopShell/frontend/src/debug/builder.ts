import type { DebugAttachment } from '../desktop';
export type Segment = {
    id: string;
    type: 'text' | 'at' | 'reply' | 'face' | 'image' | 'record' | 'video' | 'file';
    value: string;
    attachment?: DebugAttachment;
};
let sequence = 0;
export const newSegment = (type: Segment['type'] = 'text'): Segment => ({
    id: `segment-${++sequence}`,
    type,
    value: '',
});
export function buildMessage(segments: Segment[], forward: boolean) {
    const values = segments.map((s) => ({
        type: s.type,
        data:
            s.type === 'text'
                ? { text: s.value }
                : s.type === 'at'
                  ? { qq: s.value }
                  : s.type === 'face' || s.type === 'reply'
                    ? { id: s.value }
                    : { file: s.attachment?.token || '' },
    }));
    return forward ? values.map((s) => ({ type: 'node', data: { content: [s] } })) : values;
}
