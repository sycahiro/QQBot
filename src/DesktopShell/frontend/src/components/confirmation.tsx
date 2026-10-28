import { uiTransition } from '../motion';
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
import { AnimatePresence, motion, useReducedMotion } from 'motion/react';
import { CircleAlert, Trash2, X } from 'lucide-react';
import { lockModalBackground } from './modal-background';

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
                createPortal(
                    <AnimatePresence>
                        {request && (
                            <Confirmation key="confirmation" request={request} settle={settle} />
                        )}
                    </AnimatePresence>,
                    document.body,
                )}
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
    request: Request;
    settle: (accepted: boolean) => void;
}) {
    const dialog = useRef<HTMLDivElement>(null),
        id = useId(),
        reduced = useReducedMotion();
    useEffect(() => {
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
    }, [settle]);
    const Icon = request.danger ? Trash2 : CircleAlert;
    return (
        <motion.div
            className="window-dialog-backdrop confirmation-backdrop"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={uiTransition(reduced)}
        >
            <motion.div
                ref={dialog}
                className="ui-card window-close-dialog confirmation-dialog"
                role="dialog"
                aria-modal="true"
                aria-labelledby={id}
                aria-describedby={id + '-body'}
                initial={reduced ? false : { opacity: 0, y: 12, scale: 0.97 }}
                animate={{ opacity: 1, y: 0, scale: 1 }}
                exit={{ opacity: 0, y: 6, scale: 0.98 }}
                transition={uiTransition(reduced)}
            >
                <button
                    type="button"
                    className="icon-button window-dialog-dismiss"
                    aria-label="取消操作"
                    onClick={() => settle(false)}
                >
                    <X size={18} />
                </button>
                <span className={'empty-icon' + (request.danger ? ' confirmation-danger' : '')}>
                    <Icon size={26} />
                </span>
                <h2 id={id}>{request.title || '确认操作'}</h2>
                <p id={id + '-body'} tabIndex={0}>
                    {request.message}
                </p>
                <div className="window-close-choices">
                    <button
                        type="button"
                        className="qq-refresh"
                        data-cancel
                        onClick={() => settle(false)}
                    >
                        取消
                    </button>
                    <button
                        type="button"
                        className={
                            'qq-refresh ' + (request.danger ? 'danger-button' : 'primary-button')
                        }
                        onClick={() => settle(true)}
                    >
                        {request.confirmLabel || '继续'}
                    </button>
                </div>
            </motion.div>
        </motion.div>
    );
}
