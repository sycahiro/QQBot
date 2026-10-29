import { useEffect, useId, useLayoutEffect, useRef, useState, type KeyboardEvent } from 'react';
import { createPortal } from 'react-dom';
import { Check, ChevronDown, Search } from 'lucide-react';
import { usePresence } from './presence';

type Option = { value: string; label: string };
type Props = {
    label: string;
    value: string;
    options: Option[];
    onChange: (value: string) => void;
    editable?: boolean;
    disabled?: boolean;
    placeholder?: string;
    emptyText?: string;
};

/** Shared desktop combobox. The editable variant also accepts unlisted values. */
export function Select({
    label,
    value,
    options,
    onChange,
    editable = false,
    disabled = false,
    placeholder,
    emptyText = '暂无选项',
}: Props) {
    const id = useId(),
        listId = `${id}-list`;
    const anchor = useRef<HTMLDivElement>(null),
        popup = useRef<HTMLDivElement>(null);
    const control = useRef<HTMLInputElement | HTMLButtonElement | null>(null);
    const [open, setOpen] = useState(false),
        [query, setQuery] = useState(''),
        [active, setActive] = useState(-1);
    const [position, setPosition] = useState({
        left: 0,
        top: 0,
        width: 0,
        maxHeight: 280,
        above: false,
    });
    const filtered = options.filter((option) =>
        option.label.toLocaleLowerCase().includes(query.toLocaleLowerCase()),
    );
    const activeIndex = active >= 0 && active < filtered.length ? active : -1;
    const { mounted, leaving } = usePresence(open && !disabled);

    const show = () => {
        if (disabled) return;
        setQuery('');
        setActive(options.findIndex((option) => option.value === value));
        setOpen(true);
    };
    const choose = (option: Option) => {
        if (disabled) return;
        onChange(option.value);
        setOpen(false);
        control.current?.focus({ preventScroll: true });
    };
    useEffect(() => {
        if (disabled) setOpen(false);
    }, [disabled]);

    useLayoutEffect(() => {
        if (!open) return;
        const place = () => {
            const rect = anchor.current!.getBoundingClientRect();
            const below = window.innerHeight - rect.bottom - 16,
                above = rect.top - 16;
            const upwards = below < Math.min(240, filtered.length * 40 + 46) && above > below;
            setPosition({
                left: Math.max(8, Math.min(rect.left, window.innerWidth - rect.width - 8)),
                top: upwards ? window.innerHeight - rect.top + 6 : rect.bottom + 6,
                width: Math.min(rect.width, window.innerWidth - 16),
                maxHeight: Math.max(60, Math.min(280, upwards ? above : below)),
                above: upwards,
            });
        };
        place();
        const scroll = (event: Event) => {
            if (!popup.current?.contains(event.target as Node)) setOpen(false);
        };
        window.addEventListener('resize', place);
        window.addEventListener('scroll', scroll, true);
        return () => {
            window.removeEventListener('resize', place);
            window.removeEventListener('scroll', scroll, true);
        };
    }, [open, filtered.length]);

    useEffect(() => {
        if (!open) return;
        const outside = (event: PointerEvent) => {
            if (
                !anchor.current?.contains(event.target as Node) &&
                !popup.current?.contains(event.target as Node)
            )
                setOpen(false);
        };
        document.addEventListener('pointerdown', outside);
        return () => document.removeEventListener('pointerdown', outside);
    }, [open]);
    useEffect(() => {
        if (open && activeIndex >= 0)
            popup.current
                ?.querySelector(`[data-index="${activeIndex}"]`)
                ?.scrollIntoView({ block: 'nearest' });
    }, [open, activeIndex]);

    const keyDown = (event: KeyboardEvent) => {
        if (disabled || event.nativeEvent.isComposing) return;
        if (event.key === 'Escape') {
            if (open) {
                event.preventDefault();
                event.stopPropagation();
                setOpen(false);
            }
        } else if (event.key === 'Tab') setOpen(false);
        else if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
            event.preventDefault();
            if (!open) show();
            else
                setActive(
                    !filtered.length
                        ? -1
                        : activeIndex < 0
                          ? event.key === 'ArrowDown'
                              ? 0
                              : filtered.length - 1
                          : (activeIndex + (event.key === 'ArrowDown' ? 1 : -1) + filtered.length) %
                            filtered.length,
                );
        } else if (open && (event.key === 'Home' || event.key === 'End') && !editable) {
            event.preventDefault();
            setActive(event.key === 'Home' ? 0 : filtered.length - 1);
        } else if (event.key === 'Enter' || (!editable && event.key === ' ')) {
            event.preventDefault();
            if (!open && !editable) show();
            else if (open && activeIndex >= 0) choose(filtered[activeIndex]);
            else setOpen(false);
        }
    };
    const aria = {
        role: 'combobox' as const,
        'aria-label': label,
        'aria-expanded': open,
        'aria-controls': open ? listId : undefined,
        'aria-haspopup': 'listbox' as const,
        'aria-activedescendant': open && activeIndex >= 0 ? `${id}-${activeIndex}` : undefined,
    };

    return (
        <div
            ref={anchor}
            className="ui-select"
            data-open={open || undefined}
            onBlur={(event) => {
                if (
                    !event.currentTarget.contains(event.relatedTarget) &&
                    !popup.current?.contains(event.relatedTarget)
                )
                    setOpen(false);
            }}
        >
            {editable ? (
                <input
                    {...aria}
                    disabled={disabled}
                    ref={(node) => {
                        control.current = node;
                    }}
                    className="ui-select-input"
                    autoComplete="off"
                    spellCheck={false}
                    aria-autocomplete="list"
                    value={value}
                    placeholder={placeholder}
                    onFocus={show}
                    onClick={() => {
                        if (!open) show();
                    }}
                    onKeyDown={keyDown}
                    onChange={(event) => {
                        onChange(event.target.value);
                        setQuery(event.target.value);
                        setActive(-1);
                        setOpen(true);
                    }}
                />
            ) : (
                <button
                    {...aria}
                    disabled={disabled}
                    ref={(node) => {
                        control.current = node;
                    }}
                    type="button"
                    className="ui-select-trigger"
                    onClick={() => (open ? setOpen(false) : show())}
                    onKeyDown={keyDown}
                >
                    <span>
                        {options.find((option) => option.value === value)?.label ||
                            value ||
                            placeholder}
                    </span>
                </button>
            )}
            <button
                type="button"
                disabled={disabled}
                className="ui-select-arrow"
                aria-label={`${open ? '收起' : '展开'}${label}`}
                tabIndex={-1}
                onMouseDown={(event) => event.preventDefault()}
                onClick={() => {
                    if (open) setOpen(false);
                    else {
                        control.current?.focus({ preventScroll: true });
                        show();
                    }
                }}
            >
                <span className={'ui-select-chevron' + (open ? ' is-open' : '')}>
                    <ChevronDown size={16} />
                </span>
            </button>
            {typeof document !== 'undefined' &&
                mounted &&
                createPortal(
                    <div
                        ref={popup}
                        className={'ui-select-popup' + (leaving ? ' is-leaving' : '')}
                        data-origin={position.above ? 'bottom' : 'top'}
                        style={{
                            position: 'fixed',
                            left: position.left,
                            width: position.width,
                            maxHeight: position.maxHeight,
                            ...(position.above ? { bottom: position.top } : { top: position.top }),
                        }}
                    >
                        {editable && (
                            <div className="ui-select-hint">
                                <Search size={13} />
                                <span>输入搜索，也可直接使用输入的值</span>
                            </div>
                        )}
                        <div
                            id={listId}
                            role="listbox"
                            aria-label={label}
                            className="ui-select-options"
                        >
                            {filtered.map((option, index) => (
                                <div
                                    key={option.value}
                                    id={`${id}-${index}`}
                                    role="option"
                                    aria-selected={option.value === value}
                                    data-index={index}
                                    data-active={index === activeIndex || undefined}
                                    className="ui-select-option"

                                    onPointerMove={() => setActive(index)}
                                    onMouseDown={(event) => event.preventDefault()}
                                    onClick={() => choose(option)}
                                >
                                    <span>{option.label}</span>
                                    {option.value === value && <Check size={15} />}
                                </div>
                            ))}
                        </div>
                        {!filtered.length && (
                            <p className="ui-select-empty" role="status">
                                {query && options.length
                                    ? '没有匹配选项，可直接使用输入的值'
                                    : emptyText}
                            </p>
                        )}
                    </div>,
                    document.body,
                )}
        </div>
    );
}
