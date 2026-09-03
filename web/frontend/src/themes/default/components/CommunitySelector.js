import React, { useState, useRef, useEffect, useCallback } from 'react';
import styled from "styled-components";
import { HiChevronDown } from "react-icons/hi2";
import Storage from '../../../utils/Storage';
import { getAllowedTags } from '../../../utils/ContentTags';
import Api from '../../../utils/api';
import {
    communityLabel,
    isValidCommunitySlug,
    sanitizeCommunitySlug,
    splitJoinedCommunitiesForComposer,
    stripCommunityPrefix,
} from '../../../utils/community';
import { useViewerCuratorCommunities } from '../../../logic/useViewerCuratorMembership';

const Container = styled.div`
    position: relative;
    width: 100%;
`;

/*
 * default `CommunitySelector` — neutral pill trigger.
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

const CommunityName = styled.span`
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

const ListDivider = styled.div`
    height: 1px;
    margin: 0.35rem 0.9rem;
    background: ${({ theme }) => theme.colors.border};
`;

const CommunityItem = styled.div`
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

const CommunityItemName = styled.span`
    font-size: 0.75rem;
    font-weight: 500;
    color: inherit;
`;

const CommunityItemMeta = styled.span`
    font-size: 0.62rem;
    color: ${({ theme }) => theme.colors.subtleText};
    margin-left: auto;
`;

const CommunityMetaGroup = styled.div`
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

const CreateNewItem = styled(CommunityItem)`
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

const ValidationError = styled.div`
    padding: 0.35rem 0.85rem 0.1rem;
    color: ${({ theme }) => theme.colors.voteDown};
    font-size: 0.62rem;
`;

const CACHE_TTL_MS = 60 * 1000; // short-term cache for communities

const FLAG_LABELS = {
    sensitive: 'Sensitive',
    gore: 'Gore',
    violence: 'Violence',
    death: 'Death',
    adult: 'Adult'
};

export const CommunitySelector = ({ value, onChange, maxLength, minLength, disabled, 'aria-label': ariaLabel = 'Community' }) => {
    const [isOpen, setIsOpen] = useState(false);
    const [searchValue, setSearchValue] = useState('');
    const [followedCommunities, setFollowedCommunities] = useState([]);
    const [allCommunities, setAllCommunities] = useState([]);
    const [communityCounts, setCommunityCounts] = useState({});
    const [communityFlags, setCommunityFlags] = useState({});
    const [communityDominant, setCommunityDominant] = useState({});
    const [searchResults, setSearchResults] = useState([]);
    const [isSearching, setIsSearching] = useState(false);
    const [highlightedIndex, setHighlightedIndex] = useState(-1);
    const [isLoading, setIsLoading] = useState(false);
    const [validationError, setValidationError] = useState('');

    const containerRef = useRef(null);
    const searchInputRef = useRef(null);
    const dropdownRef = useRef(null);
    const searchRequestId = useRef(0);

    const effectiveMaxLength = Number.isFinite(maxLength) ? maxLength : 50;
    const effectiveMinLength = Number.isFinite(minLength) ? minLength : 3;
    const minSearchLength = Math.max(2, effectiveMinLength);

    const applyCommunities = useCallback((communitiesWithCounts = []) => {
        const communities = communitiesWithCounts.map(t => t.community).filter(t => t && t !== 'all');
        const counts = communitiesWithCounts.reduce((acc, t) => {
            acc[t.community] = t.count;
            return acc;
        }, {});
        const flags = communitiesWithCounts.reduce((acc, t) => {
            acc[String(t.community || '').toLowerCase()] = t.flags || {};
            return acc;
        }, {});
        const dominant = communitiesWithCounts.reduce((acc, t) => {
            acc[String(t.community || '').toLowerCase()] = t.dominant_tag || '';
            return acc;
        }, {});

        setAllCommunities(communities);
        setCommunityCounts(counts);
        setCommunityFlags(flags);
        setCommunityDominant(dominant);
    }, []);

    const maybeLoadCachedCommunities = useCallback(() => {
        try {
            const cached = Storage.load("communities", null);
            if (!cached || !cached.lastFetched || !Array.isArray(cached.communitiesWithCounts)) return false;
            const age = Date.now() - new Date(cached.lastFetched).getTime();
            if (age > CACHE_TTL_MS) return false;
            const allowed = new Set(getAllowedTags());
            const filtered = cached.communitiesWithCounts.filter((t) => {
                const dom = String(t?.dominant_tag || '').toLowerCase();
                return !dom || allowed.has(dom);
            });
            applyCommunities(filtered);
            return true;
        } catch (_) {
            return false;
        }
    }, [applyCommunities]);

    const sanitize = useCallback(
        (val) => sanitizeCommunitySlug(val, effectiveMaxLength),
        [effectiveMaxLength],
    );

    const viewerAddress = Storage.load('publicKey', '') || '';
    const { communities: curatedCommunities } = useViewerCuratorCommunities();

    // Load followed communities and all communities (use short-term cache, then refresh)
    useEffect(() => {
        const loadCommunities = async () => {
            const hadCache = maybeLoadCachedCommunities();
            setIsLoading(!hadCache);
            try {
                if (viewerAddress) {
                    const joined = await Api.get('communities', { joined_by: viewerAddress, limit: 100 });
                    const slugs = Array.isArray(joined?.items)
                        ? joined.items.map(i => String(i.community || '').trim()).filter(Boolean)
                        : [];
                    setFollowedCommunities(slugs);
                }

                try {
                    const data = await Api.get('communities', { limit: 100 });
                    if (data && Array.isArray(data.items)) {
                        const communitiesWithCounts = data.items
                            .filter(t => t && t.community && typeof t.community === 'string' && t.community.trim() !== '')
                            .map(t => ({
                                community: t.community,
                                count: t.post_count,
                                flags: {},
                                dominant_tag: '',
                                dominant_ratio: 0
                            }));
                        Storage.save("communities", {
                            communities: communitiesWithCounts.map(t => t.community),
                            communitiesWithCounts,
                            lastFetched: new Date().toISOString()
                        });

                        applyCommunities(communitiesWithCounts);
                    }
                } catch (_) { }
            } catch (_) { }
            setIsLoading(false);
        };

        if (isOpen) {
            loadCommunities();
        }
    }, [isOpen, viewerAddress, maybeLoadCachedCommunities, applyCommunities]);

    // Focus search input when dropdown opens
    useEffect(() => {
        if (isOpen && searchInputRef.current) {
            setTimeout(() => searchInputRef.current?.focus(), 50);
        }

        // When opening, show the current community in the search box so it isn't blank
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

    // Filter communities based on search (strip leading # for matching)
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
                        community: t.community,
                        count: t.post_count,
                        flags: {},
                        dominant_tag: '',
                        dominant_ratio: 0
                    }))
                    .sort((a, b) => (b.count - a.count) || String(a.community).localeCompare(String(b.community)));
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
            if (t && t.community) {
                map[String(t.community).toLowerCase()] = t;
            }
        });
        return map;
    }, [searchResults]);

    const { curated: curatedSlugs, joined: joinedSlugs } = React.useMemo(
        () => splitJoinedCommunitiesForComposer(followedCommunities, curatedCommunities),
        [followedCommunities, curatedCommunities],
    );
    const ownSlugSet = React.useMemo(() => {
        const set = new Set();
        for (const slug of curatedSlugs) set.add(slug);
        for (const slug of joinedSlugs) set.add(slug);
        return set;
    }, [curatedSlugs, joinedSlugs]);

    useEffect(() => {
        if (!isOpen) return;
        console.debug('[CommunitySelector] grouped communities', {
            curated: curatedSlugs,
            joined: joinedSlugs,
        });
    }, [isOpen, curatedSlugs, joinedSlugs]);

    const filteredCurated = curatedSlugs.filter(t => t.includes(searchLower));
    const filteredJoined = joinedSlugs.filter(t => t.includes(searchLower));
    const hasOwnCommunities = filteredCurated.length > 0 || filteredJoined.length > 0;

    const filteredAll = showSearchResults
        ? searchResults.filter(t => {
            const community = String(t.community || '').toLowerCase();
            return community.includes(searchLower) && !ownSlugSet.has(community);
        })
        : allCommunities
            .filter(t =>
                t.toLowerCase().includes(searchLower) && !ownSlugSet.has(t.toLowerCase())
            )
            .sort((a, b) => (communityCounts[b] || 0) - (communityCounts[a] || 0))
            .slice(0, 20)
            .map(community => ({
                community,
                count: communityCounts[community] || 0,
                flags: communityFlags[String(community).toLowerCase()] || {},
                dominant_tag: communityDominant[String(community).toLowerCase()] || ''
            }));

    const filteredAllCommunities = filteredAll.map(t => t.community || t);

    // Check if search term is a valid new community (not existing, meets length requirements)
    const isNewCommunity = isValidCommunitySlug(
        sanitizedSearch,
        effectiveMinLength,
        effectiveMaxLength,
    ) &&
        !allCommunities.map(t => t.toLowerCase()).includes(sanitizedSearch) &&
        !ownSlugSet.has(sanitizedSearch) &&
        !filteredAllCommunities.map(t => String(t || '').toLowerCase()).includes(sanitizedSearch);

    // Build flat list for keyboard navigation
    const allItems = [
        ...filteredCurated.map(t => ({ type: 'followed', community: t })),
        ...filteredJoined.map(t => ({ type: 'followed', community: t })),
        ...filteredAllCommunities.map(t => ({ type: 'all', community: t })),
        ...(isNewCommunity ? [{ type: 'new', community: sanitizedSearch }] : [])
    ];

    const getCommunityFlags = useCallback((community) => {
        const key = String(community || '').toLowerCase();
        if (searchMeta[key] && searchMeta[key].flags) {
            return searchMeta[key].flags || {};
        }
        return communityFlags[key] || {};
    }, [searchMeta, communityFlags]);

    const getCommunityCount = useCallback((community) => {
        const key = String(community || '').toLowerCase();
        if (searchMeta[key]) {
            return searchMeta[key].count || 0;
        }
        return communityCounts[community] || 0;
    }, [searchMeta, communityCounts]);

    const getFlagLabels = useCallback((community) => {
        const flags = getCommunityFlags(community);
        return Object.entries(flags || {})
            .filter(([, val]) => !!val)
            .map(([k]) => FLAG_LABELS[k] || k);
    }, [getCommunityFlags]);

    const getCommunityMeta = useCallback((community) => {
        const key = String(community || '').toLowerCase();
        const searchEntry = searchMeta[key];
        if (searchEntry) {
            return {
                flags: searchEntry.flags || {},
                dominant_tag: searchEntry.dominant_tag || ''
            };
        }
        return {
            flags: communityFlags[key] || {},
            dominant_tag: communityDominant[key] || ''
        };
    }, [searchMeta, communityFlags, communityDominant]);

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

    const handleSelect = (community, focusNext = false, isNew = false) => {
        const sanitized = sanitize(community);
        if (!isValidCommunitySlug(sanitized, effectiveMinLength, effectiveMaxLength)) {
            setValidationError(
                `Use ${effectiveMinLength}–${effectiveMaxLength} lowercase letters, numbers, or single internal hyphens`,
            );
            return;
        }
        if (isNew) console.debug('[CommunitySelector] selected new slug', { slug: sanitized });
        onChange({
            target: { value: sanitized },
            meta: { ...getCommunityMeta(community), isNew: !!isNew },
        });
        setIsOpen(false);
        setSearchValue('');
        setHighlightedIndex(-1);
        setValidationError('');
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
                handleSelect(sanitizedSearch, true, isNewCommunity);
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
                handleSelect(pick.community, true, pick.type === 'new');
            } else if (sanitizedSearch) {
                handleSelect(sanitizedSearch, true, isNewCommunity);
            } else {
                setValidationError(
                    `Use ${effectiveMinLength}–${effectiveMaxLength} lowercase letters, numbers, or single internal hyphens`,
                );
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
                    aria-label={ariaLabel}
                    aria-haspopup="listbox"
                    aria-expanded={false}
                >
                    <ButtonContent>
                        {value ? (
                            <CommunityName>{communityLabel(value)}</CommunityName>
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
                            setValidationError('');
                        }}
                        onKeyDown={handleKeyDown}
                        autoComplete="off"
                        autoCorrect="off"
                        autoCapitalize="off"
                        spellCheck={false}
                        aria-label={ariaLabel}
                        aria-haspopup="listbox"
                        aria-expanded={true}
                    />
                    {validationError && <ValidationError role="alert">{validationError}</ValidationError>}
                    <Dropdown>
                        <ResultsContainer ref={dropdownRef}>
                            {isLoading ? (
                                <EmptyState>Loading communities…</EmptyState>
                            ) : isSearching && showSearchResults && searchResults.length === 0 ? (
                                <EmptyState>Searching communities…</EmptyState>
                            ) : (
                                <>
                                    {hasOwnCommunities && (
                                        <>
                                            <SectionHeader>Your communities</SectionHeader>
                                            {filteredCurated.map((community) => {
                                                itemIndex++;
                                                const idx = itemIndex;
                                                const count = getCommunityCount(community);
                                                const flagLabels = getFlagLabels(community);
                                                return (
                                                    <CommunityItem
                                                        key={`curated-${community}`}
                                                        data-item-index={idx}
                                                        $highlighted={highlightedIndex === idx}
                                                        onClick={() => handleSelect(community)}
                                                    >
                                                        <CommunityItemName>{communityLabel(community)}</CommunityItemName>
                                                        <CommunityMetaGroup>
                                                            {flagLabels.length > 0 && (
                                                                <FlagBadge>{flagLabels.join(', ')}</FlagBadge>
                                                            )}
                                                            {count > 0 && (
                                                                <CommunityItemMeta>{formatCount(count)}</CommunityItemMeta>
                                                            )}
                                                        </CommunityMetaGroup>
                                                    </CommunityItem>
                                                );
                                            })}
                                            {filteredCurated.length > 0 && filteredJoined.length > 0 && (
                                                <ListDivider role="separator" />
                                            )}
                                            {filteredJoined.map((community) => {
                                                itemIndex++;
                                                const idx = itemIndex;
                                                const count = getCommunityCount(community);
                                                const flagLabels = getFlagLabels(community);
                                                return (
                                                    <CommunityItem
                                                        key={`joined-${community}`}
                                                        data-item-index={idx}
                                                        $highlighted={highlightedIndex === idx}
                                                        onClick={() => handleSelect(community)}
                                                    >
                                                        <CommunityItemName>{communityLabel(community)}</CommunityItemName>
                                                        <CommunityMetaGroup>
                                                            {flagLabels.length > 0 && (
                                                                <FlagBadge>{flagLabels.join(', ')}</FlagBadge>
                                                            )}
                                                            {count > 0 && (
                                                                <CommunityItemMeta>{formatCount(count)}</CommunityItemMeta>
                                                            )}
                                                        </CommunityMetaGroup>
                                                    </CommunityItem>
                                                );
                                            })}
                                        </>
                                    )}

                                    {filteredAll.length > 0 && (
                                        <>
                                            <SectionHeader>
                                                {searchLower ? 'Search Results' : 'Popular communities'}
                                            </SectionHeader>
                                            {filteredAll.map((communityObj) => {
                                                itemIndex++;
                                                const idx = itemIndex;
                                                const community = communityObj.community || communityObj;
                                                const count = typeof communityObj.count === 'number' ? communityObj.count : getCommunityCount(community);
                                                const flagLabels = getFlagLabels(community);
                                                return (
                                                    <CommunityItem
                                                        key={`all-${community}`}
                                                        data-item-index={idx}
                                                        $highlighted={highlightedIndex === idx}
                                                        onClick={() => handleSelect(community)}
                                                    >
                                                        <CommunityItemName>{communityLabel(community)}</CommunityItemName>
                                                        <CommunityMetaGroup>
                                                            {flagLabels.length > 0 && (
                                                                <FlagBadge>{flagLabels.join(', ')}</FlagBadge>
                                                            )}
                                                            {count > 0 && (
                                                                <CommunityItemMeta>{formatCount(count)}</CommunityItemMeta>
                                                            )}
                                                        </CommunityMetaGroup>
                                                    </CommunityItem>
                                                );
                                            })}
                                        </>
                                    )}

                                    {isNewCommunity && (
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

                                    {!isLoading && !hasOwnCommunities && filteredAll.length === 0 && !isNewCommunity && (
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

export default CommunitySelector;
