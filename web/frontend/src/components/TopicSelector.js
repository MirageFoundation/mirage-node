import React, { useState, useRef, useEffect, useCallback } from 'react';
import styled from "styled-components";
import Storage from '../utils/Storage';
import Api from '../lib/api';
import { fetchFollowedTopics } from '../utils/Subscriptions';

const Container = styled.div`
    position: relative;
    width: 100%;
`;

const SelectorButton = styled.button`
    display: flex;
    align-items: center;
    justify-content: space-between;
    width: 100%;
    padding: 0.5rem 0.75rem;
    border: 1px solid ${({ theme }) => theme?.colors?.border || '#444'};
    border-radius: 8px;
    background-color: ${({ theme }) => theme?.colors?.panelAlt || '#1f2328'};
    color: ${({ theme }) => theme?.colors?.text || '#FFFFFF'};
    font-size: 0.85rem;
    cursor: pointer;
    transition: all 0.2s ease;
    text-align: left;

    &:hover:not(:disabled) {
        border-color: ${({ theme }) => theme?.colors?.subtleText || '#666'};
    }
    
    &:focus {
        outline: none;
        border-color: #667eea;
        box-shadow: 0 0 0 3px rgba(102, 126, 234, 0.15);
    }

    &:disabled {
        opacity: 0.5;
        cursor: not-allowed;
    }
`;

const ButtonContent = styled.div`
    display: flex;
    align-items: center;
    gap: 0.15rem;
    min-width: 0;
    overflow: hidden;
`;

const TopicIcon = styled.span`
    font-size: 0.9rem;
    flex-shrink: 0;
`;

const TopicName = styled.span`
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
`;

const Placeholder = styled.span`
    color: ${({ theme }) => theme?.colors?.subtleText || '#888'};
`;

const ChevronIcon = styled.span`
    font-size: 0.6rem;
    flex-shrink: 0;
    margin-left: 0.5rem;
`;

const SearchInputWrapper = styled.div`
    position: relative;
    width: 100%;
`;

const SearchInput = styled.input`
    width: 100%;
    padding: 0.5rem 0.75rem;
    border: 1px solid #667eea;
    border-radius: 8px;
    background-color: ${({ theme }) => theme?.colors?.panelAlt || '#1f2328'};
    color: ${({ theme }) => theme?.colors?.text || '#FFFFFF'};
    font-size: 0.85rem;
    outline: none;
    box-shadow: 0 0 0 3px rgba(102, 126, 234, 0.15);

    &::placeholder {
        color: ${({ theme }) => theme?.colors?.subtleText || '#888'};
    }
`;

const Dropdown = styled.div`
    position: absolute;
    top: calc(100% + 4px);
    left: 0;
    right: 0;
    background-color: ${({ theme }) => theme?.colors?.panel || '#23272C'};
    border: 1px solid ${({ theme }) => theme?.colors?.border || '#444'};
    border-radius: 8px;
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.3);
    z-index: 1000;
    max-height: 280px;
    display: flex;
    flex-direction: column;
    overflow: hidden;
`;

const ResultsContainer = styled.div`
    overflow-y: auto;
    flex: 1;
`;

const SectionHeader = styled.div`
    padding: 0.4rem 0.75rem;
    font-size: 0.65rem;
    font-weight: 600;
    color: ${({ theme }) => theme?.colors?.subtleText || '#888'};
    text-transform: uppercase;
    letter-spacing: 0.05em;
    background-color: ${({ theme }) => theme?.colors?.panelAlt || '#1f2328'};
    position: sticky;
    top: 0;
`;

const TopicItem = styled.div`
    display: flex;
    align-items: center;
    gap: 0.2rem;
    padding: 0.5rem 0.75rem;
    cursor: pointer;
    transition: background-color 0.15s ease;
    background-color: ${({ $highlighted, theme }) =>
        $highlighted ? (theme?.colors?.accent || 'rgba(102, 126, 234, 0.15)') : 'transparent'};

    &:hover {
        background-color: ${({ theme }) => theme?.colors?.accent || 'rgba(102, 126, 234, 0.15)'};
    }
`;

const TopicItemIcon = styled.span`
    font-size: 0.85rem;
    color: ${({ theme }) => theme?.colors?.subtleText || '#888'};
`;

const TopicItemName = styled.span`
    font-size: 0.85rem;
    color: ${({ theme }) => theme?.colors?.text || '#fff'};
`;

const TopicItemMeta = styled.span`
    font-size: 0.7rem;
    color: ${({ theme }) => theme?.colors?.subtleText || '#888'};
    margin-left: auto;
`;

const TopicMetaGroup = styled.div`
    margin-left: auto;
    display: flex;
    align-items: center;
    gap: 0.35rem;
`;

const FlagBadge = styled.span`
    padding: 2px 6px;
    border-radius: 6px;
    background-color: rgba(255, 99, 71, 0.12);
    color: #ff7b6b;
    font-size: 0.68rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.04em;
`;

const CreateNewItem = styled(TopicItem)`
    border-top: 1px solid ${({ theme }) => theme?.colors?.border || '#444'};
    background-color: ${({ $highlighted }) =>
        $highlighted ? 'rgba(102, 126, 234, 0.15)' : 'rgba(102, 126, 234, 0.05)'};
    
    &:hover {
        background-color: rgba(102, 126, 234, 0.2);
    }
`;

const CreateNewLabel = styled.span`
    font-size: 0.8rem;
    color: #667eea;
    font-weight: 500;
`;

const EmptyState = styled.div`
    padding: 1rem 0.75rem;
    text-align: center;
    color: ${({ theme }) => theme?.colors?.subtleText || '#888'};
    font-size: 0.8rem;
`;

const CACHE_TTL_MS = 60 * 1000; // short-term cache for topics

const FLAG_LABELS = {
    sensitive: 'Sensitive',
    gore: 'Gore',
    violence: 'Violence',
    death: 'Death',
    porn: 'Porn'
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
            applyTopics(cached.topicsWithCounts);
            return true;
        } catch (_) {
            return false;
        }
    }, [applyTopics]);

    const sanitize = useCallback((val) => {
        try {
            const s = String(val || '')
                .replace(/[^a-zA-Z0-9]/g, '')
                .toLowerCase();
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
                    const followed = await fetchFollowedTopics(viewerAddress);
                    setFollowedTopics(followed || []);
                }

                // Always fetch fresh from backend - it filters by min/max topic size
                try {
                    const data = await Api.get('get_topics', { limit: 100 }, { timeoutMs: 10000 });
                    if (data && Array.isArray(data.topics)) {
                        const topicsWithCounts = data.topics
                            .filter(t => t && t.topic && typeof t.topic === 'string' && t.topic.trim() !== '')
                            .map(t => ({
                                topic: t.topic,
                                count: t.post_count || t.count || 0,
                                flags: t.flags || {},
                                dominant_tag: t.dominant_tag || '',
                                dominant_ratio: t.dominant_ratio || 0
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
    const searchLower = searchValue.toLowerCase().trim().replace(/^#+/, '');
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
                const data = await Api.get('search_topics', { q: sanitizedSearch, limit: 20 }, { timeoutMs: 8000 });
                if (searchRequestId.current !== requestId) return;
                const topics = Array.isArray(data?.topics) ? data.topics : [];
                const normalized = topics
                    .filter(t => t && t.topic && typeof t.topic === 'string')
                    .map(t => ({
                        topic: t.topic,
                        count: t.post_count || t.count || 0,
                        flags: t.flags || {},
                        dominant_tag: t.dominant_tag || '',
                        dominant_ratio: t.dominant_ratio || 0
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
        ...(isNewTopic ? [{ type: 'create', topic: sanitizedSearch }] : [])
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

    const handleSelect = (topic, focusNext = false) => {
        const sanitized = sanitize(topic);
        onChange({ target: { value: sanitized }, meta: getTopicMeta(topic) });
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
                handleSelect(sanitizedSearch, true);
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
                handleSelect(allItems[highlightedIndex].topic, true);
            } else if (sanitizedSearch) {
                handleSelect(sanitizedSearch, true);
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
                            <>
                                <TopicIcon>#</TopicIcon>
                                <TopicName>{value}</TopicName>
                            </>
                        ) : (
                            <Placeholder>Select a topic</Placeholder>
                        )}
                    </ButtonContent>
                    <ChevronIcon>▼</ChevronIcon>
                </SelectorButton>
            ) : (
                <SearchInputWrapper>
                    <SearchInput
                        ref={searchInputRef}
                        type="text"
                        placeholder="Search or create"
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
                                <EmptyState>Loading topics...</EmptyState>
                            ) : isSearching && showSearchResults && searchResults.length === 0 ? (
                                <EmptyState>Searching topics...</EmptyState>
                            ) : (
                                <>
                                    {filteredFollowed.length > 0 && (
                                        <>
                                            <SectionHeader>Your Topics</SectionHeader>
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
                                                        <TopicItemIcon>#</TopicItemIcon>
                                                        <TopicItemName>{topic}</TopicItemName>
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
                                                {searchLower ? 'Search Results' : 'Popular Topics'}
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
                                                        <TopicItemIcon>#</TopicItemIcon>
                                                        <TopicItemName>{topic}</TopicItemName>
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
                                        <>
                                            {(filteredFollowed.length > 0 || filteredAll.length > 0) && (
                                                <SectionHeader>Create New</SectionHeader>
                                            )}
                                            {(() => {
                                                itemIndex++;
                                                const idx = itemIndex;
                                                return (
                                                    <CreateNewItem
                                                        data-item-index={idx}
                                                        $highlighted={highlightedIndex === idx}
                                                        onClick={() => handleSelect(sanitizedSearch)}
                                                    >
                                                        <TopicItemIcon>+</TopicItemIcon>
                                                        <CreateNewLabel>Create #{sanitizedSearch}</CreateNewLabel>
                                                    </CreateNewItem>
                                                );
                                            })()}
                                        </>
                                    )}

                                    {!isLoading && filteredFollowed.length === 0 && filteredAll.length === 0 && !isNewTopic && (
                                        <EmptyState>
                                            {searchLower ? 'No topics found. Type to create a new one.' : 'Start typing to search or create a topic.'}
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
