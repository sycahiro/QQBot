/** 状态文案切换时做一次短促的淡入，避免状态直接跳变。 */
export function StatusSwap({ text, className }: { text: string; className?: string }) {
    return (
        <span key={text} className={'status-swap' + (className ? ' ' + className : '')}>
            {text}
        </span>
    );
}
