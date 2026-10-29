import { useId, useState, type ReactNode } from 'react';
import { ChevronDown } from 'lucide-react';

/** Keep the content clipped throughout opening/closing, and unfocusable when shut. */
export function Disclosure({
    title,
    children,
    className = '',
    defaultOpen = false,
}: {
    title: ReactNode;
    children: ReactNode;
    className?: string;
    defaultOpen?: boolean;
}) {
    const [open, setOpen] = useState(defaultOpen);
    const id = useId();
    return (
        <div className={`ui-disclosure ${className}`}>
            <button
                type="button"
                className="disclosure-trigger"
                aria-expanded={open}
                aria-controls={id}
                onClick={() => setOpen((value) => !value)}
            >
                <span className={'disclosure-chevron' + (open ? ' is-open' : '')}>
                    <ChevronDown size={15} />
                </span>
                <span>{title}</span>
            </button>
            <div
                id={id}
                className="disclosure-panel"
                inert={!open}
                aria-hidden={!open}
                style={{ gridTemplateRows: open ? '1fr' : '0fr', opacity: open ? 1 : 0 }}
            >
                <div className="disclosure-clip">
                    <div className="disclosure-content">{children}</div>
                </div>
            </div>
        </div>
    );
}
