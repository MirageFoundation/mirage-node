import React, { useState, useRef, useEffect, useCallback } from 'react';
import styled from "styled-components";
import { HiChevronDown } from "react-icons/hi2";
import Storage from '../../../utils/Storage';
import { getAllowedTags } from '../../../utils/ContentTags';
import Api from '../../../utils/api';
import { communityLabel, stripCommunityPrefix } from '../../../utils/community';

const Container = styled.div`
    position: relative;
    width: 100%;
`;

/*
 * default `TopicSelector` — neutral pill trigger.
 *
 * Design follows R5 (neutral input focus), R6 (HiChevronDown) and R7
 * (0.75rem / 500 input typography). Trigger height matches the search
 * input that replaces it on click (2.1rem) so the layout doesn't jump.
 */
const CONTROL_HEIGHT = '2.1rem';

const SelectorButton = styled.button`
    display: inline-flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.4rem;
    height: ${CONTROL_HEIGHT};
    padding: 0 0.85rem;
    border: 1px solid ${({ theme }) => theme.colors.border};
    border-radius: 9999px;
    background-color: transparent;
    color: ${({ theme }) => theme.colors.text};
    font-size: 0.75rem;
    font-weight: 500;
    font-family: inherit;
    line-height: 1.2;
    cursor: pointer;
    transition: border-color 0.15s ease, background-color 0.15s ease;
    text-align: left;
    box-sizing: border-box;
    margin: 0;
    max-width: 100%;

    &:hover:not(:disabled) {
        border-color: ${({ theme }) => theme.colors.borderStrong};
        background-color: ${({ theme }) => theme.colors.hoverBg};
    }

    &:focus {
        outline: none;
        border-color: ${({ theme }) => theme.colors.borderStrong};
        box-shadow: none;
    }

    &:disabled {
        opacity: 0.5;
        cursor: not-allowed;
    }
`;

const ButtonContent = styled.div`
    display: flex;
    align-items: center;
    gap: 0.3rem;
    min-width: 0;
    overflow: hidden;
`;

const TopicName = styled.span`
    font-size: inherit;
    line-height: inherit;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
`;

const Placeholder = styled.span`
    font-size: inherit;
    line-height: inherit;
    color: ${({ theme }) => theme.colors.subtleText};
    font-weight: 500;
`;

const ChevronWrap = styled.span`
    display: inline-flex;
    align-items: center;
    justify-content: center;
    font-size: 0.9rem;
    color: ${({ theme }) => theme.colors.subtleText};
    flex-shrink: 0;
    transition: transform 0.15s ease;
    transform: rotate(${({ $expanded }) => ($expanded ? "180deg" : "0deg")});
`;

const SearchInputWrapper = styled.div`
    position: relative;
    width: 100%;
`;

/* Search input that replaces the trigger — same height, same padding so
 * clicking the pill doesn't shift the layout. R5 focus. R7 typography. */
const SearchInput = styled.input`
    width: 100%;
    height: ${CONTROL_HEIGHT};
    padding: 0 0.85rem;
    border: 1px solid ${({ theme }) => theme.colors.border};
    border-radius: 9999px;
    background-color: ${({ theme }) => theme.colors.bg};
    color: ${({ theme }) => theme.colors.text};
    font-size: 0.75rem;
    font-weight: 500;
    font-family: inherit;
    line-height: 1.2;
    outline: none;
    box-sizing: border-box;
    box-shadow: none;
    transition: border-color 0.15s ease;

    &::placeholder {
        color: ${({ theme }) => theme.colors.subtleText};
        font-weight: 500;
    }

    &:hover:not(:disabled) {
        border-color: ${({ theme }) => theme.colors.borderStrong};
    }

    &:focus {
        outline: none;
        border-color: ${({ theme }) => theme.colors.borderStrong};
        box-shadow: none;
    }
`;

/* Dropdown sheet — styled after `SearchDropdown`.
 * Canvas: `menuBg`. Rows: `sidebarItemText` at rest → `menuSelectedBg`
 * tile + `menuItemHoverText` on hover/highlight. */
const Dropdown = styled.div`
    position: absolute;
    top: calc(100% + 6px);
    left: 0;
    right: 0;
    background-color: ${({ theme }) => theme.colors.menuBg};
    border: 1px solid ${({ theme }) => theme.colors.border};
    border-radius: 12px;
    box-shadow: 0 12px 32px rgba(0, 0, 0, 0.28);
    z-index: 1000;
    max-height: min(60vh, 420px);
    display: flex;
    flex-direction: column;
    overflow: hidden;
    padding: 0.25rem 0;
`;

const ResultsContainer = styled.div`
    overflow-y: auto;
    flex: 1;
    scrollbar-width: thin;
    scrollbar-color: ${({ theme }) => theme.colors.scrollbar} transparent;

    &::-webkit-scrollbar { width: 8px; }
    &::-webkit-scrollbar-thumb {
        background: ${({ theme }) => theme.colors.scrollbar};
        border-radius: 4px;
    }
`;

const SectionHeader = styled.div`
    padding: 0.45rem 0.9rem 0.2rem;
    font-size: 0.55rem;
    font-weight: 500;
    color: ${({ theme }) => theme.colors.menuHeaderText};
    text-transform: uppercase;
    letter-spacing: 0.05em;
    background-color: transparent;
`;

const TopicItem = styled.div`
    display: flex;
    align-items: center;
    gap: 0.6rem;
    padding: 0.45rem 0.9rem;
    cursor: pointer;
    transition: background-color 0.15s ease, color 0.15s ease;
    color: ${({ theme }) => theme.colors.sidebarItemText};
    background-color: ${({ $highlighted, theme }) =>
        $highlighted ? theme.colors.menuSelectedBg : 'transparent'};

    &:hover {
        background-color: ${({ theme }) => theme.colors.menuSelectedBg};
        color: ${({ theme }) => theme.colors.menuItemHoverText};
    }
`;

const TopicItemName = styled.span`
    font-size: 0.75rem;
    font-weight: 500;
    color: inherit;
`;

const TopicItemMeta = styled.span`
    font-size: 0.62rem;
    color: ${({ theme }) => theme.colors.subtleText};
    margin-left: auto;
`;

const TopicMetaGroup = styled.div`
    margin-left: auto;
    display: flex;
    align-items: center;
    gap: 0.35rem;
`;

const FlagBadge = styled.span`
    padding: 1px 5px;
    border-radius: 6px;
    background-color: ${({ theme }) => theme.colors.voteDownBg};
    color: ${({ theme }) => theme.colors.voteDown};
    font-size: 0.55rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.04em;
`;

/* Wraps the "Create New" section (header + create row) so we can draw the
 * divider ABOVE the section header rather than on the row itself. */
const CreateNewSection = styled.div`
    border-top: 1px solid ${({ theme }) => theme.colors.border};
    margin-top: 0.25rem;
    padding-top: 0.25rem;
`;

const CreateNewItem = styled(TopicItem)`
    color: ${({ theme }) => theme.colors.followBtnBg};

    &:hover {
        background-color: ${({ theme }) => theme.colors.menuSelectedBg};
        color: ${({ theme }) => theme.colors.followBtnBg};
    }
`;

const CreateNewIcon = styled.span`
    flex-shrink: 0;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 22px;
    height: 22px;
    font-size: 0.9rem;
    font-weight: 600;
    color: ${({ theme }) => theme.colors.followBtnBg};
`;

const CreateNewLabel = styled.span`
    font-size: 0.75rem;
    color: inherit;
    font-weight: 600;
`;

const EmptyState = styled.div`
    padding: 0.65rem 0.9rem;
    text-align: center;
    color: ${({ theme }) => theme.colors.subtleText};
    font-size: 0.7rem;
`;

const CACHE_TTL_MS = 60 * 1000; // short-term cache for topics

const FLAG_LABELS = {
    sensitive: 'Sensitive',
    gore: 'Gore',
    violence: 'Violence',
    death: 'Death',
    adult: 'Adult'
};

export const TopicSelector = ({ value, onChange, maxLength, minLength, disabled }) => {
    const [isOpen, setIsOpen] = useState(false);
    const [searchValue, setSearchValue] = useState('');
    const [followedTopics, setFollowedTopics] = useState([]);
    const [allTopics, setAllTopics] = useState([]);
    const [topicCounts, setTopicCounts] = useState({});
    const [topicFlags, setTopicFlags] = useState({});
    const [topicDominant, setTopicDominant] = useState({});
    const [searchResults, setSearchResults] = useState([]);
    const [isSearching, setIsSearching] = useState(false);
    const [highlightedIndex, setHighlightedIndex] = useState(-1);
    const [isLoading, setIsLoading] = useState(false);

    const containerRef = useRef(null);
    const searchInputRef = useRef(null);
    const dropdownRef = useRef(null);
    const searchRequestId = useRef(0);

    const effectiveMaxLength = Number.isFinite(maxLength) ? maxLength : 50;
    const effectiveMinLength = Number.isFinite(minLength) ? minLength : 3;
    const minSearchLength = Math.max(2, effectiveMinLength);

    const applyTopics = useCallback((topicsWithCounts = []) => {
        const topics = topicsWithCounts.map(t => t.topic).filter(t => t && t !== 'all');
        const counts = topicsWithCounts.reduce((acc, t) => {
            acc[t.topic] = t.count;
            return acc;
        }, {});
        const flags = topicsWithCounts.reduce((acc, t) => {
            acc[String(t.topic || '').toLowerCase()] = t.flags || {};
            return acc;
        }, {});
        const dominant = topicsWithCounts.reduce((acc, t) => {
            acc[String(t.topic || '').toLowerCase()] = t.dominant_tag || '';
            return acc;
        }, {});

        setAllTopics(topics);
        setTopicCounts(counts);
        setTopicFlags(flags);
        setTopicDominant(dominant);
    }, []);

    const maybeLoadCachedTopics = useCallback(() => {
        try {
            const cached = Storage.load("topics", null);
            if (!cached || !cached.lastFetched || !Array.isArray(cached.topicsWithCounts)) return false;
            const age = Date.now() - new Date(cached.lastFetched).getTime();
            if (age > CACHE_TTL_MS) return false;
            const allowed = new Set(getAllowedTags());
            const filtered = cached.topicsWithCounts.filter((t) => {
                const dom = String(t?.dominant_tag || '').toLowerCase();
                return !dom || allowed.has(dom);
            });
            applyTopics(filtered);
            return true;
        } catch (_) {
            return false;
        }
    }, [applyTopics]);

    const sanitize = useCallback((val) => {
        try {
            const s = String(val || '')
                .toLowerCase()
                .replace(/[^a-z0-9-]/g, '')
                .replace(/--+/g, '-')
                .replace(/^-+|-+$/g, '');
            return s.slice(0, effectiveMaxLength);
        } catch (_) {
            return '';
        }
    }, [effectiveMaxLength]);

    const viewerAddress = Storage.load('publicKey', '') || '';

    // Load followed topics and all topics (use short-term cache, then refresh)
    useEffect(() => {
        const loadTopics = async () => {
            const hadCache = maybeLoadCachedTopics();
            setIsLoading(!hadCache);
            try {
                if (viewerAddress) {
                    const joined = await Api.get('communities', { joined_by: viewerAddress, limit: 100 });
                    const slugs = Array.isArray(joined?.items)
                        ? joined.items.map(i => String(i.community || '').trim()).filter(Boolean)
                        : [];
                    setFollowedTopics(slugs);
                }

                try {
                    const data = await Api.get('communities', { limit: 100 });
                    if (data && Array.isArray(data.items)) {
                        const topicsWithCounts = data.items
                            .filter(t => t && t.community && typeof t.community === 'string' && t.community.trim() !== '')
                            .map(t => ({
                                topic: t.community,
                                count: 0,
                                flags: {},
                                dominant_tag: '',
                                dominant_ratio: 0
                            }));
                        Storage.save("topics", {
                            topics: topicsWithCounts.map(t => t.topic),
                            topicsWithCounts,
                            lastFetched: new Date().toISOString()
                        });

                        applyTopics(topicsWithCounts);
                    }
                } catch (_) { }
            } catch (_) { }
            setIsLoading(false);
        };

        if (isOpen) {
            loadTopics();
        }
    }, [isOpen, viewerAddress, maybeLoadCachedTopics, applyTopics]);

    // Focus search input when dropdown opens
    useEffect(() => {
        if (isOpen && searchInputRef.current) {
            setTimeout(() => searchInputRef.current?.focus(), 50);
        }

        // When opening, show the current topic in the search box so it isn't blank
        if (isOpen) {
            const current = String(value || '').trim();
            if (current && !searchValue) {
                setSearchValue(current);
            }
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [isOpen]);

    // Close dropdown on click outside
    useEffect(() => {
        const handleClickOutside = (e) => {
            if (containerRef.current && !containerRef.current.contains(e.target)) {
                setIsOpen(false);
                setSearchValue('');
                setHighlightedIndex(-1);
            }
        };
        document.addEventListener('mousedown', handleClickOutside);
        return () => document.removeEventListener('mousedown', handleClickOutside);
    }, []);

    // Filter topics based on search (strip leading # for matching)
    const searchLower = stripCommunityPrefix(searchValue.toLowerCase());
    const sanitizedSearch = sanitize(searchValue);
    const showSearchResults = isOpen && sanitizedSearch.length >= minSearchLength;

    useEffect(() => {
        if (!showSearchResults) {
            setSearchResults([]);
            setIsSearching(false);
            return;
        }

        const requestId = searchRequestId.current + 1;
        searchRequestId.current = requestId;
        setIsSearching(true);

        const handle = setTimeout(async () => {
            try {
                const data = await Api.get('communities', { query: sanitizedSearch, limit: 20 }, { timeoutMs: 8000 });
                if (searchRequestId.current !== requestId) return;
                const items = Array.isArray(data?.items) ? data.items : [];
                const normalized = items
                    .filter(t => t && t.community && typeof t.community === 'string')
                    .map(t => ({
                        topic: t.community,
                        count: 0,
                        flags: {},
                        dominant_tag: '',
                        dominant_ratio: 0
                    }));
                setSearchResults(normalized);
            } catch (_) {
                if (searchRequestId.current !== requestId) return;
                setSearchResults([]);
            } finally {
                if (searchRequestId.current === requestId) {
                    setIsSearching(false);
                }
            }
        }, 250);

        return () => {
            searchRequestId.current += 1;
            clearTimeout(handle);
        };
    }, [showSearchResults, sanitizedSearch, minSearchLength]);

    const searchMeta = React.useMemo(() => {
        const map = {};
        searchResults.forEach(t => {
            if (t && t.topic) {
                map[String(t.topic).toLowerCase()] = t;
            }
        });
        return map;
    }, [searchResults]);

    const filteredFollowed = followedTopics.filter(t =>
        t.toLowerCase().includes(searchLower)
    );

    const filteredAll = showSearchResults
        ? searchResults.filter(t => {
            const topic = String(t.topic || '');
            return topic.toLowerCase().includes(searchLower) &&
                !followedTopics.map(ft => ft.toLowerCase()).includes(topic.toLowerCase());
        })
        : allTopics
            .filter(t =>
                t.toLowerCase().includes(searchLower) && !followedTopics.includes(t)
            )
            .sort((a, b) => (topicCounts[b] || 0) - (topicCounts[a] || 0))
            .slice(0, 20)
            .map(topic => ({
                topic,
                count: topicCounts[topic] || 0,
                flags: topicFlags[String(topic).toLowerCase()] || {},
                dominant_tag: topicDominant[String(topic).toLowerCase()] || ''
            }));

    const filteredAllTopics = filteredAll.map(t => t.topic || t);

    // Check if search term is a valid new topic (not existing, meets length requirements)
    const isNewTopic = sanitizedSearch.length >= effectiveMinLength &&
        sanitizedSearch.length <= effectiveMaxLength &&
        !allTopics.map(t => t.toLowerCase()).includes(sanitizedSearch) &&
        !followedTopics.map(t => t.toLowerCase()).includes(sanitizedSearch) &&
        !filteredAllTopics.map(t => String(t || '').toLowerCase()).includes(sanitizedSearch);

    // Build flat list for keyboard navigation
    const allItems = [
        ...filteredFollowed.map(t => ({ type: 'followed', topic: t })),
        ...filteredAllTopics.map(t => ({ type: 'all', topic: t })),
        ...(isNewTopic ? [{ type: 'new', topic: sanitizedSearch }] : [])
    ];

    const getTopicFlags = useCallback((topic) => {
        const key = String(topic || '').toLowerCase();
        if (searchMeta[key] && searchMeta[key].flags) {
            return searchMeta[key].flags || {};
        }
        return topicFlags[key] || {};
    }, [searchMeta, topicFlags]);

    const getTopicCount = useCallback((topic) => {
        const key = String(topic || '').toLowerCase();
        if (searchMeta[key]) {
            return searchMeta[key].count || 0;
        }
        return topicCounts[topic] || 0;
    }, [searchMeta, topicCounts]);

    const getFlagLabels = useCallback((topic) => {
        const flags = getTopicFlags(topic);
        return Object.entries(flags || {})
            .filter(([, val]) => !!val)
            .map(([k]) => FLAG_LABELS[k] || k);
    }, [getTopicFlags]);

    const getTopicMeta = useCallback((topic) => {
        const key = String(topic || '').toLowerCase();
        const searchEntry = searchMeta[key];
        if (searchEntry) {
            return {
                flags: searchEntry.flags || {},
                dominant_tag: searchEntry.dominant_tag || ''
            };
        }
        return {
            flags: topicFlags[key] || {},
            dominant_tag: topicDominant[key] || ''
        };
    }, [searchMeta, topicFlags, topicDominant]);

    const focusNextInput = useCallback(() => {
        setTimeout(() => {
            const form = containerRef.current?.closest('form');
            if (form) {
                const inputs = form.querySelectorAll('input:not([type="hidden"]):not([type="checkbox"]), textarea');
                const currentIdx = Array.from(inputs).findIndex(el => containerRef.current?.contains(el));
                const nextInput = inputs[currentIdx + 1];
                if (nextInput) nextInput.focus();
            }
        }, 0);
    }, []);

    const handleSelect = (topic, focusNext = false, isNew = false) => {
        const sanitized = sanitize(topic);
        if (isNew) console.debug('[TopicSelector] selected new slug', { slug: sanitized });
        onChange({
            target: { value: sanitized },
            meta: { ...getTopicMeta(topic), isNew: !!isNew },
        });
        setIsOpen(false);
        setSearchValue('');
        setHighlightedIndex(-1);
        if (focusNext) focusNextInput();
    };

    const handleKeyDown = (e) => {
        if (!isOpen) {
            if (e.key === 'Enter' || e.key === ' ' || e.key === 'ArrowDown') {
                e.preventDefault();
                setIsOpen(true);
            }
            return;
        }

        if (e.key === 'Escape') {
            e.preventDefault();
            setIsOpen(false);
            setSearchValue('');
            setHighlightedIndex(-1);
            return;
        }

        if (e.key === 'Tab') {
            e.preventDefault();
            // Close dropdown and move focus to next input (title)
            if (sanitizedSearch && sanitizedSearch.length >= effectiveMinLength) {
                handleSelect(sanitizedSearch, true, isNewTopic);
            } else {
                setIsOpen(false);
                setSearchValue('');
                setHighlightedIndex(-1);
                focusNextInput();
            }
            return;
        }

        if (e.key === 'ArrowDown') {
            e.preventDefault();
            setHighlightedIndex(prev => Math.min(prev + 1, allItems.length - 1));
        } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            setHighlightedIndex(prev => Math.max(prev - 1, -1));
        } else if (e.key === 'Enter') {
            e.preventDefault();
            if (highlightedIndex >= 0 && highlightedIndex < allItems.length) {
                const pick = allItems[highlightedIndex];
                handleSelect(pick.topic, true, pick.type === 'new');
            } else if (sanitizedSearch) {
                handleSelect(sanitizedSearch, true, isNewTopic);
            }
        }
    };

    // Scroll highlighted item into view
    useEffect(() => {
        if (highlightedIndex >= 0 && dropdownRef.current) {
            const items = dropdownRef.current.querySelectorAll('[data-item-index]');
            if (items[highlightedIndex]) {
                items[highlightedIndex].scrollIntoView({
                    block: 'nearest',
                    behavior: 'smooth'
                });
            }
        }
    }, [highlightedIndex]);

    const formatCount = (count) => {
        if (!count) return '';
        if (count >= 1000) return `${(count / 1000).toFixed(1)}k posts`;
        return `${count} posts`;
    };

    let itemIndex = -1;

    return (
        <Container ref={containerRef}>
            {!isOpen ? (
                <SelectorButton
                    type="button"
                    onClick={() => !disabled && setIsOpen(true)}
                    onKeyDown={handleKeyDown}
                    disabled={disabled}
                >
                    <ButtonContent>
                        {value ? (
                            <TopicName>{communityLabel(value)}</TopicName>
                        ) : (
                            <Placeholder>Select a community</Placeholder>
                        )}
                    </ButtonContent>
                    <ChevronWrap aria-hidden="true" $expanded={false}>
                        <HiChevronDown />
                    </ChevronWrap>
                </SelectorButton>
            ) : (
                <SearchInputWrapper>
                    <SearchInput
                        ref={searchInputRef}
                        type="text"
                        placeholder="Search or enter a community slug"
                        value={searchValue}
                        onChange={(e) => {
                            setSearchValue(e.target.value);
                            setHighlightedIndex(-1);
                        }}
                        onKeyDown={handleKeyDown}
                        autoComplete="off"
                        autoCorrect="off"
                        autoCapitalize="off"
                        spellCheck={false}
                    />
                    <Dropdown>
                        <ResultsContainer ref={dropdownRef}>
                            {isLoading ? (
                                <EmptyState>Loading communities...</EmptyState>
                            ) : isSearching && showSearchResults && searchResults.length === 0 ? (
                                <EmptyState>Searching communities...</EmptyState>
                            ) : (
                                <>
                                    {filteredFollowed.length > 0 && (
                                        <>
                                            <SectionHeader>Your communities</SectionHeader>
                                            {filteredFollowed.map((topic) => {
                                                itemIndex++;
                                                const idx = itemIndex;
                                                const count = getTopicCount(topic);
                                                const flagLabels = getFlagLabels(topic);
                                                return (
                                                    <TopicItem
                                                        key={`followed-${topic}`}
                                                        data-item-index={idx}
                                                        $highlighted={highlightedIndex === idx}
                                                        onClick={() => handleSelect(topic)}
                                                    >
                                                        <TopicItemName>{communityLabel(topic)}</TopicItemName>
                                                        <TopicMetaGroup>
                                                            {flagLabels.length > 0 && (
                                                                <FlagBadge>{flagLabels.join(', ')}</FlagBadge>
                                                            )}
                                                            {count > 0 && (
                                                                <TopicItemMeta>{formatCount(count)}</TopicItemMeta>
                                                            )}
                                                        </TopicMetaGroup>
                                                    </TopicItem>
                                                );
                                            })}
                                        </>
                                    )}

                                    {filteredAll.length > 0 && (
                                        <>
                                            <SectionHeader>
                                                {searchLower ? 'Search Results' : 'Popular communities'}
                                            </SectionHeader>
                                            {filteredAll.map((topicObj) => {
                                                itemIndex++;
                                                const idx = itemIndex;
                                                const topic = topicObj.topic || topicObj;
                                                const count = typeof topicObj.count === 'number' ? topicObj.count : getTopicCount(topic);
                                                const flagLabels = getFlagLabels(topic);
                                                return (
                                                    <TopicItem
                                                        key={`all-${topic}`}
                                                        data-item-index={idx}
                                                        $highlighted={highlightedIndex === idx}
                                                        onClick={() => handleSelect(topic)}
                                                    >
                                                        <TopicItemName>{communityLabel(topic)}</TopicItemName>
                                                        <TopicMetaGroup>
                                                            {flagLabels.length > 0 && (
                                                                <FlagBadge>{flagLabels.join(', ')}</FlagBadge>
                                                            )}
                                                            {count > 0 && (
                                                                <TopicItemMeta>{formatCount(count)}</TopicItemMeta>
                                                            )}
                                                        </TopicMetaGroup>
                                                    </TopicItem>
                                                );
                                            })}
                                        </>
                                    )}

                                    {isNewTopic && (
                                        <CreateNewSection>
                                            <SectionHeader>New slug</SectionHeader>
                                            {(() => {
                                                itemIndex++;
                                                const idx = itemIndex;
                                                return (
                                                    <CreateNewItem
                                                        data-item-index={idx}
                                                        $highlighted={highlightedIndex === idx}
                                                        onClick={() => handleSelect(sanitizedSearch, false, true)}
                                                    >
                                                        <CreateNewIcon>+</CreateNewIcon>
                                                        <CreateNewLabel>Use {communityLabel(sanitizedSearch)}</CreateNewLabel>
                                                    </CreateNewItem>
                                                );
                                            })()}
                                        </CreateNewSection>
                                    )}

                                    {!isLoading && filteredFollowed.length === 0 && filteredAll.length === 0 && !isNewTopic && (
                                        <EmptyState>
                                            {searchLower ? 'No listed community found. Use any valid slug.' : 'Start typing to search or enter a community slug.'}
                                        </EmptyState>
                                    )}
                                </>
                            )}
                        </ResultsContainer>
                    </Dropdown>
                </SearchInputWrapper>
            )}
        </Container>
    );
};

export default TopicSelector;
