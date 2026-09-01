import React, { useState, useEffect, useRef } from 'react';
import styled from 'styled-components';
import { communityLabel } from '../../../utils/community';

const FilterBarWrapper = styled.div`
    position: relative;
    width: ${props => props.inline ? 'auto' : '100%'};
    display: ${props => props.inline ? 'inline-flex' : 'block'};
`;

const StyledFilterSection = styled.div`
    display: flex;
    margin-top: 0.15rem;
    color: ${({ theme }) => theme.colors.text};
    text-decoration: none;
    font-weight: bold;
    flex-wrap: wrap;
    align-items: baseline;
    width: ${props => props.inline ? 'auto' : '100%'};
    margin-left: 0;
    margin-right: 0;
    padding-left: ${props => props.inline ? '0' : '1.1rem'};
    padding-right: ${props => props.inline ? '0' : '1rem'};
    @media (max-width: 1000px) {
        padding-left: ${props => props.inline ? '0' : '0.25rem'};
        padding-right: ${props => props.inline ? '0' : '0.25rem'};
    }
`;

const Separator = styled.span`
    color: ${({ theme }) => theme.colors.subtleText};
    font-size: 0.5rem;
    line-height: 1;
    user-select: none;
    pointer-events: none;
    margin: 0 0.125rem;
    display: inline-flex;
    align-items: center;
    vertical-align: middle;
`;

const FilterItem = styled.span`
    display: inline-flex;
    align-items: baseline;
    white-space: nowrap;
    vertical-align: baseline;
`;

const Label = styled.span`
    color: ${({ theme, $textStyle }) => $textStyle === 'subtle'
        ? (theme.colors.subtleText)
        : (theme.colors.text)};
    font-weight: ${({ $textStyle }) => $textStyle === 'subtle' ? '500' : '700'};
    font-size: ${({ $textStyle }) => $textStyle === 'subtle' ? '0.68rem' : '0.72rem'};
    font-family: inherit;
    margin-right: 0.3rem;
    letter-spacing: 0.01em;
`;

// removed unused DropdownLabel

const SelectWrapper = styled.span`
    position: relative;
    display: inline-flex;
    vertical-align: baseline;
    padding-bottom: 0;
    margin-bottom: 0;
    
    &::after {
        content: '';
        position: absolute;
        left: 0;
        width: 100%;
        height: 0.04rem;
        background-color: ${({ theme }) => theme.colors.link};
        bottom: -0.05rem;
        pointer-events: none;
        transition: background-color 0.2s ease;
        display: block;
    }
    
    &:hover::after {
        background-color: ${({ theme }) => theme.colors.linkHover};
    }
    
    @media (max-width: 1000px) {
        &::after { right: auto; }
    }
`;

const HiddenMeasure = styled.span`
    position: absolute;
    visibility: hidden;
    white-space: nowrap;
    font-weight: 700;
    font-size: ${({ $textStyle }) => $textStyle === 'subtle' ? '0.68rem' : '0.72rem'};
    font-family: inherit;
    padding: 0;
    margin: 0;
`;

const StyledSelect = styled.select`
    color: ${({ theme }) => theme.colors.link};
    background-color: transparent;
    border: none;
    font-weight: 700;
    font-size: ${({ $textStyle }) => $textStyle === 'subtle' ? '0.68rem' : '0.72rem'};
    font-family: inherit;
    cursor: pointer;
    padding: 0;
    margin: 0;
    appearance: none;
    outline: none;
    width: ${props => props.width || 'auto'};
    vertical-align: baseline;
    line-height: 1.2;
    position: relative;
    z-index: 1;

    option {
        background-color: ${({ theme }) => theme.colors.panel};
        color: ${({ theme }) => theme.colors.text};
        font-family: inherit;
        font-weight: 700;
        font-size: ${({ $textStyle }) => $textStyle === 'subtle' ? '0.68rem' : '0.72rem'};
    }
`;

const InlineLink = styled.a`
    background: none;
    border: none;
    padding: 0;
    margin: 0;
    color: ${({ theme }) => theme.colors.subtleText};
    font-weight: 700;
    font-size: ${({ $textStyle }) => $textStyle === 'subtle' ? '0.68rem' : '0.72rem'};
    font-family: inherit;
    cursor: pointer;
    text-decoration: none;
    &:hover {
        color: ${({ theme }) => theme.colors.text};
        text-decoration: none;
    }
`;

const InlineParen = styled.span`
    color: ${({ theme }) => theme.colors.subtleText};
    font-weight: 500;
    font-size: ${({ $textStyle }) => $textStyle === 'subtle' ? '0.68rem' : '0.72rem'};
    font-family: inherit;
    margin-left: 0.3rem;
`;

function FilterBar({
    currentTab,
    onTabClick,
    onSortChange,
    selectedSort,
    customCommunityName,
    inline = false,
    prefixLabel = '',
    textStyle = 'normal',
    subscribedCommunities = [],
    hasFollowedUsers = false,
    rightActionLabel = null,
    onRightAction = null
}) {
    const communityOptions = {
        'all': 'all communities',
        'home': 'home feed',
        'following': 'following feed',
        // 'popular': 'popular communities', // disabled for now
        'manage': 'manage subscriptions'
    };

    const sortOptions = {
        'magic': 'sorted by magic',
        'points': 'sorted by points',
        'newest': 'sorted by newest'
    };

    const [selectedCommunity, setSelectedCommunity] = useState(customCommunityName || currentTab || 'all');
    const [sortBy, setSortBy] = useState('magic');

    const communityMeasureRef = useRef(null);
    const sortMeasureRef = useRef(null);
    const [communityWidth, setCommunityWidth] = useState('auto');
    const [sortWidth, setSortWidth] = useState('auto');

    const selectedValue = customCommunityName
        ? customCommunityName
        : ((() => {
            const hasSubs = (Array.isArray(subscribedCommunities) && subscribedCommunities.length > 0) || hasFollowedUsers;
            const allowed = ['all', 'home', 'following', ...(hasSubs ? ['manage'] : [])];
            return allowed.includes(selectedCommunity) ? selectedCommunity : 'all';
        })());
    const communityDisplayText = customCommunityName ? communityLabel(customCommunityName) : (communityOptions[selectedValue] || 'all communities');
    const sortDisplayText = sortOptions[sortBy] || 'sorted by newest';

    useEffect(() => {
        const validCommunities = ['all', 'home', 'following', /* 'popular', */ 'manage']; // popular disabled for now
        if (customCommunityName) {
            setSelectedCommunity(customCommunityName);
        } else if (currentTab && validCommunities.includes(currentTab)) {
            setSelectedCommunity(currentTab);
        } else if (!currentTab) {
            setSelectedCommunity('all');
        }
    }, [customCommunityName, currentTab]);

    useEffect(() => {
        const measureWidth = () => {
            if (communityMeasureRef.current) {
                const width = communityMeasureRef.current.offsetWidth;
                setCommunityWidth(`${width}px`);
            }
            if (sortMeasureRef.current) {
                const width = sortMeasureRef.current.offsetWidth;
                setSortWidth(`${width}px`);
            }
        };
        measureWidth();
        const timeoutId = setTimeout(measureWidth, 0);
        return () => clearTimeout(timeoutId);
    }, [communityDisplayText, sortDisplayText, customCommunityName]);

    // Sync local sort state with external selection (from MainView)
    useEffect(() => {
        if (selectedSort && (selectedSort === 'magic' || selectedSort === 'points' || selectedSort === 'newest')) {
            setSortBy(selectedSort);
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [selectedSort]);

    const handleCommunityChange = (e) => {
        const value = e.target.value;
        if (value === 'divider') return;
        setSelectedCommunity(value);
        if (onTabClick) {
            onTabClick(value);
        }
    };

    const handleSortChange = (e) => {
        const value = e.target.value;
        setSortBy(value);
        if (onSortChange) {
            onSortChange(value);
        }
    };

    return (
        <FilterBarWrapper inline={inline}>
            <StyledFilterSection inline={inline}>
                {prefixLabel ? (
                    <FilterItem>
                        <Label $textStyle={textStyle}>{prefixLabel}</Label>
                    </FilterItem>
                ) : null}
                <FilterItem>
                    <SelectWrapper $textStyle={textStyle}>
                        <HiddenMeasure $textStyle={textStyle} ref={communityMeasureRef}>{communityDisplayText}</HiddenMeasure>
                        <StyledSelect $textStyle={textStyle} value={selectedValue} onChange={handleCommunityChange} width={communityWidth}>
                            {customCommunityName ? (
                                <>
                                    <option value={customCommunityName}>{communityLabel(customCommunityName)}</option>
                                    <option disabled value="divider-custom">────</option>
                                </>
                            ) : null}
                            {(Array.isArray(subscribedCommunities) && subscribedCommunities.length > 0) || hasFollowedUsers ? (
                                <>
                                    <option value="manage">manage subscriptions</option>
                                    <option disabled value="divider">────</option>
                                </>
                            ) : null}
                            <option value="all">all communities</option>
                            <option value="home">home feed</option>
                            <option value="following">following feed</option>
                            {/* <option value="popular">popular communities</option> */}
                            {Array.isArray(subscribedCommunities) && subscribedCommunities.length > 0 ? (
                                <>
                                    <option disabled value="divider-2">────</option>
                                    {subscribedCommunities.map((t) => (
                                        <option key={`sub-${t}`} value={t}>{communityLabel(t)}</option>
                                    ))}
                                </>
                            ) : null}
                        </StyledSelect>
                    </SelectWrapper>
                    {rightActionLabel ? (
                        <InlineParen $textStyle={textStyle}>
                            (<InlineLink href="#" $textStyle={textStyle} onClick={(e) => { e.preventDefault(); if (onRightAction) onRightAction(); }}>{rightActionLabel}</InlineLink>)
                        </InlineParen>
                    ) : null}
                </FilterItem>
                <FilterItem data-sep="true">
                    <Separator>|</Separator>
                </FilterItem>
                <FilterItem>
                    <SelectWrapper $textStyle={textStyle}>
                        <HiddenMeasure $textStyle={textStyle} ref={sortMeasureRef}>{sortDisplayText}</HiddenMeasure>
                        <StyledSelect $textStyle={textStyle} value={selectedSort || sortBy} onChange={handleSortChange} width={sortWidth}>
                            <option value="magic">sorted by magic</option>
                            <option value="points">sorted by points</option>
                            <option value="newest">sorted by newest</option>
                        </StyledSelect>
                    </SelectWrapper>
                </FilterItem>
            </StyledFilterSection>
        </FilterBarWrapper>
    );
}

export default FilterBar;
