import {
    createContext,
    useCallback,
    useContext,
    useEffect,
    useId,
    useRef,
    useState,
    type ReactNode,
} from 'react';
import { createPortal } from 'react-dom';
import { CircleAlert, Trash2, X } from 'lucide-react';
import { lockModalBackground } from './modal-background';
import { usePresence } from './presence';

type Options = { title?: string; confirmLabel?: string; danger?: boolean };
type Request = Options & { message: string; owner: symbol; resolve: (value: boolean) => void };
type Confirm = (message: string, options?: Options) => Promise<boolean>;
const Context = createContext<{
    ask: (owner: symbol, message: string, options?: Options) => Promise<boolean>;
    cancel: (owner: symbol) => void;
}>({ ask: async () => false, cancel: () => {} });

/** One app-styled confirmation; requests never outlive the page that initiated them. */
export function ConfirmationProvider({ children }: { children: ReactNode }) {
    const [request, setRequest] = useState<Request | null>(null),
        pending = useRef<Request | null>(null);
    const settle = useCallback((accepted: boolean) => {
        const current = pending.current;
        if (!current) return;
        pending.current = null;
        setRequest(null);
        current.resolve(accepted);
    }, []);
    const ask = useCallback(
        (owner: symbol, message: string, options: Options = {}) =>
            new Promise<boolean>((resolve) => {
                if (pending.current) {
                    resolve(false);
                    return;
                }
                const next = { ...options, message, owner, resolve };
                pending.current = next;
                setRequest(next);
            }),
        [],
    );
    const cancel = useCallback(
        (owner: symbol) => {
            if (pending.current?.owner === owner) settle(false);
        },
        [settle],
    );
    useEffect(
        () => () => {
            pending.current?.resolve(false);
            pending.current = null;
        },
        [],
    );
    return (
        <Context.Provider value={{ ask, cancel }}>
            {children}
            {typeof document !== 'undefined' &&
                createPortal(<Confirmation request={request} settle={settle} />, document.body)}
        </Context.Provider>
    );
}

export function useConfirm(): Confirm {
    const { ask, cancel } = useContext(Context),
        owner = useRef(Symbol('confirmation-owner'));
    useEffect(() => () => cancel(owner.current), [cancel]);
    return useCallback((message, options) => ask(owner.current, message, options), [ask]);
}

function Confirmation({
    request,
    settle,
}: {
    request: Request | null;
    settle: (accepted: boolean) => void;
}) {
    const dialog = useRef<HTMLDivElement>(null),
        id = useId();
    const { mounted, leaving } = usePresence(Boolean(request));
    // Freeze the last request so the exit animation keeps its content.
    const [shown, setShown] = useState<Request | null>(null);
    useEffect(() => {
        if (request) setShown(request);
    }, [request]);
    useEffect(() => {
        if (!mounted || !shown) return;
        const root = document.getElementById('root'),
            previous = document.activeElement as HTMLElement | null;
        const unlock = lockModalBackground(root);
        const closing = () =>
            Boolean(document.querySelector('[aria-labelledby="window-close-title"]'));
        const timer = requestAnimationFrame(() => {
            if (!closing())
                dialog.current?.querySelector<HTMLButtonElement>('[data-cancel]')?.focus();
        });
        const keyboard = (event: KeyboardEvent) => {
            if (closing()) return;
            if (event.key === 'Escape') {
                event.preventDefault();
                settle(false);
            }
            if (event.key === 'Tab') {
                const buttons = Array.from(
                    dialog.current?.querySelectorAll<HTMLElement>(
                        'button:not(:disabled),[tabindex="0"]',
                    ) ?? [],
                );
                const first = buttons[0],
                    last = buttons.at(-1);
                if (!dialog.current?.contains(document.activeElement)) {
                    event.preventDefault();
                    first?.focus();
                } else if (event.shiftKey && document.activeElement === first) {
                    event.preventDefault();
                    last?.focus();
                } else if (!event.shiftKey && document.activeElement === last) {
                    event.preventDefault();
                    first?.focus();
                }
            }
        };
        document.addEventListener('keydown', keyboard);
        return () => {
            cancelAnimationFrame(timer);
            document.removeEventListener('keydown', keyboard);
            unlock();
            if (previous?.isConnected && !closing()) previous.focus();
        };
    }, [mounted, settle]);
    if (!mounted || !shown) return null;
    const Icon = shown.danger ? Trash2 : CircleAlert;
    return (
        <div
            className={
                'window-dialog-backdrop confirmation-backdrop' + (leaving ? ' is-leaving' : '')
            }
        >
            <div
                ref={dialog}
                className="ui-card window-close-dialog confirmation-dialog"
                role="dialog"
                aria-modal="true"
                aria-labelledby={id}
                aria-describedby={id + '-body'}
            >
                <button
                    type="button"
                    className="btn btn-icon window-dialog-dismiss"
                    aria-label="取消操作"
                    onClick={() => settle(false)}
                >
                    <X size={18} />
                </button>
                <span className={'empty-icon' + (shown.danger ? ' confirmation-danger' : '')}>
                    <Icon size={26} />
                </span>
                <h2 id={id}>{shown.title || '确认操作'}</h2>
                <p id={id + '-body'} tabIndex={0}>
                    {shown.message}
                </p>
                <div className="window-close-choices">
                    <button type="button" className="btn" data-cancel onClick={() => settle(false)}>
                        取消
                    </button>
                    <button
                        type="button"
                        className={'btn ' + (shown.danger ? 'btn-danger' : 'btn-primary')}
                        onClick={() => settle(true)}
                    >
                        {shown.confirmLabel || '继续'}
                    </button>
                </div>
            </div>
        </div>
    );
}
