import { useCallback, useEffect, useRef, useState } from 'react';
import styled from 'styled-components';
import Api from '../../../utils/api';
import UserAvatar from './UserAvatar.js';
import { requireThemeColor } from '../../../utils/themeColor';

/**
 * Single-line user field with the suggestion list the post editor shows after
 * `@`, for the places that ask for "a username or an address".
 *
 * Picking a suggestion writes the bare username, which is what
 * `resolveUserIdentity` already accepts, so a caller keeps taking a typed
 * address just as well as a picked name.
 */

const Wrap = styled.div`
    position: relative;
`;

const Field = styled.input.attrs({
    autoComplete: 'off',
    'data-bwignore': 'true',
    'data-1p-ignore': 'true',
    'data-lpignore': 'true',
})`
    box-sizing: border-box; width: 100%;
    padding: 0.45rem 0.55rem; border-radius: 7px; border: 1px solid ${({ theme }) => requireThemeColor(theme, 'border')};
    background: ${({ theme }) => requireThemeColor(theme, 'inputBackground')}; color: inherit;
    font: inherit; font-size: 0.75rem;
`;

const Dropdown = styled.div`
    position: absolute;
    top: calc(100% + 0.25rem);
    left: 0;
    right: 0;
    background: ${({ theme }) => requireThemeColor(theme, 'menuBg')};
    border: 1px solid ${({ theme }) => requireThemeColor(theme, 'border')};
    border-radius: 10px;
    box-shadow: 0 12px 32px rgba(0, 0, 0, 0.28);
    z-index: 40;
    max-height: min(50vh, 260px);
    overflow-y: auto;
    scrollbar-width: thin;
    scrollbar-color: ${({ theme }) => requireThemeColor(theme, 'scrollbar')} transparent;

    &::-webkit-scrollbar { width: 8px; }
    &::-webkit-scrollbar-thumb {
        background: ${({ theme }) => requireThemeColor(theme, 'scrollbar')};
        border-radius: 4px;
    }
`;

const Item = styled.div`
    display: flex;
    align-items: center;
    gap: 0.6rem;
    padding: 0.45rem 0.6rem;
    cursor: pointer;
    color: ${({ theme }) => requireThemeColor(theme, 'sidebarItemText')};
    background: ${({ $active, theme }) => ($active ? requireThemeColor(theme, 'menuSelectedBg') : 'transparent')};

    &:hover {
        background: ${({ theme }) => requireThemeColor(theme, 'menuSelectedBg')};
        color: ${({ theme }) => requireThemeColor(theme, 'menuItemHoverText')};
    }
`;

const TextCol = styled.div`
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 0.08rem;
    overflow: hidden;
`;

const Username = styled.span`
    font-size: 0.7rem;
    font-weight: 600;
    color: inherit;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
`;

const Address = styled.span`
    font-size: 0.6rem;
    font-weight: 500;
    color: ${({ theme }) => requireThemeColor(theme, 'subtleText')};
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
`;

const Hint = styled.div`
    padding: 0.5rem 0.6rem;
    color: ${({ theme }) => requireThemeColor(theme, 'subtleText')};
    font-size: 0.65rem;
    font-weight: 500;
`;

/** A typed address is not a username, so searching for one only ever says "no users found". */
const ADDRESS_PREFIX = /^mirage1/i;

export default function UserSuggestInput({
    value,
    onChange,
    disabled = false,
    placeholder,
    ariaLabel,
    required = false,
    listId = 'user-suggest',
}) {
    const [results, setResults] = useState([]);
    const [open, setOpen] = useState(false);
    const [index, setIndex] = useState(0);
    const [loading, setLoading] = useState(false);
    const wrapRef = useRef(null);
    const inputRef = useRef(null);
    const timerRef = useRef(null);
    const abortRef = useRef(null);

    const query = value.trim();
    const searchable = query.length > 0 && !ADDRESS_PREFIX.test(query);

    useEffect(() => {
        if (!open || !searchable) {
            setResults([]);
            setLoading(false);
            return undefined;
        }
        setLoading(true);
        if (timerRef.current) clearTimeout(timerRef.current);
        if (abortRef.current) {
            try { abortRef.current.abort(); } catch (_) { /* noop */ }
        }
        timerRef.current = setTimeout(async () => {
            const controller = new AbortController();
            abortRef.current = controller;
            // Same `anon-` strip the mention search does, so typing the visible
            // name finds the profile rather than nothing.
            const searchQuery = query.startsWith('anon-') ? query.slice(5) : query;
            try {
                const res = await Api.get('search_username', { q: searchQuery || query, limit: 8 }, { timeoutMs: 4000 });
                if (!controller.signal.aborted && Array.isArray(res?.results)) {
                    setResults(res.results);
                    setIndex(0);
                }
            } catch (err) {
                if (!controller.signal.aborted) {
                    console.debug('[user-suggest] search failed', { query, error: String(err) });
                    setResults([]);
                }
            } finally {
                if (!controller.signal.aborted) setLoading(false);
            }
        }, 200);
        return () => {
            if (timerRef.current) clearTimeout(timerRef.current);
        };
    }, [query, open, searchable]);

    useEffect(() => {
        if (!open) return undefined;
        const onDocMouseDown = (event) => {
            if (wrapRef.current && !wrapRef.current.contains(event.target)) setOpen(false);
        };
        document.addEventListener('mousedown', onDocMouseDown);
        return () => document.removeEventListener('mousedown', onDocMouseDown);
    }, [open]);

    const select = useCallback((username) => {
        onChange(username);
        setOpen(false);
        setResults([]);
        setIndex(0);
        requestAnimationFrame(() => {
            try { inputRef.current?.focus(); } catch (_) { /* noop */ }
        });
    }, [onChange]);

    const handleKeyDown = (event) => {
        if (open && results.length > 0) {
            if (event.key === 'ArrowDown') {
                event.preventDefault();
                setIndex((prev) => (prev + 1) % results.length);
                return;
            }
            if (event.key === 'ArrowUp') {
                event.preventDefault();
                setIndex((prev) => (prev - 1 + results.length) % results.length);
                return;
            }
            // Enter picks the highlighted user instead of submitting the form,
            // which is the whole point of having the list open.
            if (event.key === 'Enter' || event.key === 'Tab') {
                event.preventDefault();
                select(results[index].username);
                return;
            }
        }
        if (open && event.key === 'Escape') {
            event.preventDefault();
            setOpen(false);
        }
    };

    const showDropdown = open && searchable && (loading || results.length > 0);
    const activeId = results[index] ? `${listId}-${results[index].username}` : undefined;

    return (
        <Wrap ref={wrapRef}>
            <Field
                ref={inputRef}
                aria-label={ariaLabel}
                aria-autocomplete="list"
                aria-expanded={showDropdown}
                aria-controls={showDropdown ? listId : undefined}
                aria-activedescendant={showDropdown ? activeId : undefined}
                role="combobox"
                value={value}
                onChange={(event) => {
                    onChange(event.target.value);
                    setOpen(true);
                }}
                onKeyDown={handleKeyDown}
                onBlur={() => setOpen(false)}
                placeholder={placeholder}
                required={required}
                disabled={disabled}
            />
            {showDropdown && (
                <Dropdown id={listId} role="listbox">
                    {results.map((item, i) => (
                        <Item
                            key={item.username}
                            id={`${listId}-${item.username}`}
                            role="option"
                            aria-selected={i === index}
                            $active={i === index}
                            onMouseDown={(event) => {
                                // Keep the input focused; a blur here would close
                                // the list before the click landed.
                                event.preventDefault();
                                select(item.username);
                            }}
                            onMouseEnter={() => setIndex(i)}
                        >
                            <UserAvatar seed={item.username} size={24} />
                            <TextCol>
                                <Username>@{item.username}</Username>
                                {item.address ? (
                                    <Address>{`${item.address.slice(0, 8)}…${item.address.slice(-4)}`}</Address>
                                ) : null}
                            </TextCol>
                        </Item>
                    ))}
                    {loading && results.length === 0 && <Hint>Searching…</Hint>}
                </Dropdown>
            )}
        </Wrap>
    );
}
