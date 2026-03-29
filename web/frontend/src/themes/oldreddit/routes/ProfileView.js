import { Helmet } from "react-helmet-async";
import styled, { useTheme } from "styled-components";
import Button from "../components/Button.js";
import MobileHeader from "../components/MobileHeader.js";
import { ContentGrid, ModernPostFeed, TabbedContainer, ContainerBody, TabsRow, ClickableTab } from "../Layout";
import { tooltipStyles } from "../components/Tooltip.js";
import { useProfile } from "../../../logic/useProfile";
const Row = styled.div`
    display: grid;
    grid-template-columns: ${({
    theme
}) => theme.layout.formRowColumns};
    gap: ${({
    theme
}) => theme.layout.formRowGap};
    align-items: ${({
    theme
}) => theme.layout.formRowAlign};
    margin: ${({
    theme
}) => theme.layout.formRowMargin};
    @media (max-width: 1000px) {
        grid-template-columns: 1fr;
        gap: 0.35rem;
        align-items: stretch;
    }
`;
const RowCentered = styled(Row)`
    align-items: center;
`;
const Label = styled.div`
    color: ${({
    theme
}) => theme.colors.subtleText};
    font-weight: ${({
    theme
}) => theme.layout.labelWeight};
    font-size: ${({
    theme
}) => theme.layout.labelSize};
    white-space: nowrap;
    @media (max-width: 1000px) {
        margin-bottom: 0.1rem;
    }
`;
const HoverableLabel = styled.div`
    color: ${({
    theme
}) => theme.colors.subtleText};
    font-weight: ${({
    theme
}) => theme.layout.labelWeight};
    font-size: ${({
    theme
}) => theme.layout.labelSize};
    white-space: nowrap;
    ${tooltipStyles()}
    
    @media (max-width: 1000px) {
        margin-bottom: 0.1rem;
    }
`;
const ValueBox = styled.div`
    background-color: ${({
    theme
}) => theme.layout.containerBg};
    border: ${({
    theme
}) => theme.layout.containerBorder};
    border-bottom: ${({
    theme
}) => theme.layout.containerBorderBottom};
    border-radius: ${({
    theme
}) => theme.layout.containerRadius};
    padding: ${({
    theme
}) => theme.layout.cardPadding};
    width: 100%;
    box-sizing: border-box;
    overflow-x: auto;
`;
const BioTextarea = styled.textarea`
    width: 100%;
    box-sizing: border-box;
    background-color: ${({
    theme
}) => theme.colors.panelAlt};
    border: 1px solid ${({
    theme
}) => theme.colors.border};
    border-radius: ${({
    theme
}) => theme.layout.inputRadius};
    padding: ${({
    theme
}) => theme.layout.cardPadding};
    color: ${({
    theme
}) => theme.colors.text};
    font-family: inherit;
    font-size: ${({
    theme
}) => theme.layout.monoSize};
    resize: vertical;
    min-height: ${({
    theme
}) => theme.layout.textareaMinHeight};
    &:focus { outline: none; border-color: ${({
    theme
}) => theme.colors.accent}; }
`;
const ValueBoxWithButton = styled(ValueBox)`
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: ${({
    theme
}) => theme.layout.containerGap};
    flex-wrap: nowrap;
    overflow: hidden;
    @media (max-width: 1000px) {
        flex-wrap: wrap;
        gap: 0.5rem;
    }
`;
const SectionTitle = styled.div`
    margin-top: ${({
    $first,
    theme
}) => $first ? '0' : theme.layout.sectionMarginTop};
    margin-bottom: ${({
    theme
}) => theme.layout.sectionMarginBottom};
    font-weight: 700;
    color: ${({
    theme
}) => theme.colors.text};
    font-size: ${({
    theme
}) => theme.layout.sectionSize};
    display: flex;
    align-items: center;
    gap: 0.5rem;

    &::after {
        content: '';
        flex: 1;
        height: 1px;
        background: ${({
    theme
}) => theme.colors.border};
    }
`;
const FilterSelect = styled.select`
    width: 100%;
    margin-bottom: ${({
    theme
}) => theme.layout.inputMarginBottom};
    background-color: ${({
    theme
}) => theme.colors.panelAlt};
    border: 1px solid ${({
    theme
}) => theme.colors.border};
    border-radius: ${({
    theme
}) => theme.layout.inputRadius};
    padding: ${({
    theme
}) => theme.layout.inputPadding};
    color: ${({
    theme
}) => theme.colors.text};
    font-size: ${({
    theme
}) => theme.layout.inputSize};
    cursor: pointer;
    transition: all 0.2s ease;
    
    &:focus {
        outline: none;
        border-color: #667eea;
        box-shadow: ${({
    theme
}) => theme.layout.focusRing};
    }
`;
const PostsList = styled.div`
    display: flex;
    flex-direction: column;
    gap: ${({
    theme
}) => theme.layout.cardGap};
`;
const PostItem = styled.a`
    display: block;
    text-decoration: none;
    color: inherit;
    border: ${({
    theme,
    isActive
}) => theme.layout.cardBorder};
    border-bottom: ${({
    theme
}) => theme.layout.cardBorderBottom};
    background-color: ${({
    theme,
    isActive
}) => isActive ? theme.colors.accentSubtle : theme.layout.cardBg};
    border-radius: ${({
    theme
}) => theme.layout.cardRadius};
    padding: ${({
    theme
}) => theme.layout.cardPadding};
    cursor: pointer;
    transition: background-color 0.2s ease, border-color 0.2s ease;
    box-shadow: ${({
    theme,
    isActive
}) => isActive ? '0 0 12px rgba(102, 126, 234, 0.25)' : theme.layout.cardShadow};

    &:hover {
        background-color: ${({
    theme
}) => theme.colors.panelAlt};
        border-color: ${({
    theme
}) => theme.layout.cardHoverBorder};
    }
`;
const PostMeta = styled.div`
    font-size: 0.55rem;
    color: ${({
    theme
}) => theme.colors.subtleText};
    margin-bottom: 0.25rem;
    display: flex;
    flex-wrap: wrap;
    gap: 0.35rem;
`;
const PostPreview = styled.div`
    font-size: 0.65rem;
    color: ${({
    theme
}) => theme.colors.text};
    line-height: 1.3;
    word-break: break-word;
    white-space: pre-line;
`;
const Mono = styled.span`
    color: ${({
    theme
}) => theme.colors.text};
    font-size: ${({
    theme
}) => theme.layout.monoSize};
    font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
    white-space: normal;
    word-break: break-word;
    overflow-wrap: anywhere;
`;

// Single-line with ellipsis for short values (e.g., username)
const InlineMono = styled(Mono)`
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    display: block;
`;
const LoadingSpinner = styled.div`
    width: 16px;
    height: 16px;
    border: 2px solid ${({
    theme
}) => theme.colors.border};
    border-top: 2px solid ${({
    theme
}) => theme.colors.subtleText};
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
    
    @keyframes spin {
        0% { transform: rotate(0deg); }
        100% { transform: rotate(360deg); }
    }
`;
const SubtleMono = styled(Mono)`
    color: ${({
    theme
}) => theme.colors.subtleText};
`;
const LoadingRow = styled.div`
    display: flex;
    align-items: center;
    gap: 0.5rem;
    margin: 0.5rem 0 0.75rem;
    padding: 0.5rem;
    color: ${({
    theme
}) => theme.colors.subtleText};
`;

// (no footer actions here; sign out moved to header menu)

//

export default function ProfileView({
    state
}) {
    const { caps } = useTheme();
    const profileHideFilterSelect = caps.profileHideFilterSelect;
    const profilePostsFullWidth = caps.profilePostsFullWidth;
    const {
        navigate,
        theme,
        address,
        usernameResolutionError,
        isResolvingUsername,
        routeIdentity,
        profileAddress,
        isOwnProfile,
        VALID_TABS,
        activeTab,
        setActiveTab,
        profileUsesListFeed,
        FeedComponent,
        isPostsTab,
        profileUsername,
        userLevel,
        subscriptionExpiry,
        recentPosts,
        isLoadingRecentPosts,
        recentPostsError,
        activeRecentPost,
        recentPage,
        recentAutoLoading,
        recentPostsFilter,
        setRecentPostsFilter,
        recentBottomSentinelRef,
        addressCopied,
        setAddressCopied,
        isFollowingProfile,
        isFollowInProgress,
        isUnfollowAction,
        followHover,
        setFollowHover,
        myQueuePosition,
        formatStatusForPosition,
        prefsTopics,
        prefsAuthors,
        prefsLoading,
        prefsError,
        prefAuthorUsernames,
        similarUsers,
        similarUsersLoading,
        similarUsersError,
        showAllTopicPrefs,
        setShowAllTopicPrefs,
        showAllAuthorPrefs,
        setShowAllAuthorPrefs,
        showAllSimilarUsers,
        setShowAllSimilarUsers,
        biography,
        bioEditing,
        setBioEditing,
        bioDraft,
        setBioDraft,
        bioSaving,
        bioError,
        setBioError,
        bioButtonStatus,
        confirmDonate,
        donateAmountRaw,
        setDonateAmountRaw,
        donateMessage,
        formatPrefWeight,
        colorForWeight,
        hasValidAccount,
        effectivePostsFilter,
        shortenAddress,
        getTierName,
        getTierColor,
        formatSubscriptionExpiry,
        buildMetaLine,
        renderPostPreview,
        handleFollowToggle,
        getPostUrl,
        handleRecentPostClick,
        usernameDisplay,
        balanceDisplay,
        reserveDisplay,
        registeredDisplay,
        canEditProfile,
        donatePending,
        donateStatus,
        profileTitle,
        canHaveBiography,
        BIO_MAX,
        handleBioSave,
        formatDonateAmount,
        handleDonate,
        confirmDonateAction,
        cancelDonate
    } = useProfile({
        state
    });
    // Show loading/error states for username resolution
    if (isResolvingUsername || usernameResolutionError) {
        return <ContentGrid>
            <Helmet>
                <title>{routeIdentity ? `@${routeIdentity}` : 'Profile'} | Mirage</title>
            </Helmet>
            <div>
                <ModernPostFeed>
                    <MobileHeader />
                    <TabbedContainer>
                        <ContainerBody style={{
                            display: 'flex',
                            flexDirection: 'column',
                            alignItems: 'center',
                            justifyContent: 'center',
                            textAlign: 'center',
                            padding: '2rem',
                            gap: '0.5rem',
                            minHeight: '200px'
                        }}>
                            {isResolvingUsername ? <span style={{
                                color: '#888'
                            }}>Looking up @{routeIdentity}...</span> : <span style={{
                                color: '#ff6b6b'
                            }}>{usernameResolutionError}</span>}
                        </ContainerBody>
                    </TabbedContainer>
                </ModernPostFeed>
            </div>
        </ContentGrid>;
    }
    return <ContentGrid>
        <Helmet>
            <title>{profileTitle} | Mirage</title>
        </Helmet>
        <div>
            <ModernPostFeed>
                <MobileHeader />
                <TabbedContainer>
                    <TabsRow>
                        {VALID_TABS.map(tab => <ClickableTab key={tab} $active={activeTab === tab} onClick={() => setActiveTab(tab)}>
                            {tab}
                        </ClickableTab>)}
                    </TabsRow>
                    <ContainerBody $fullWidth={profilePostsFullWidth && isPostsTab}>
                        {activeTab === 'profile' && <>
                            <RowCentered>
                                <Label>Username:</Label>
                                <ValueBoxWithButton>
                                    <InlineMono title={profileUsername}>{usernameDisplay}</InlineMono>
                                    {canEditProfile && <Button onClick={() => navigate('/change_username')} size="sm" minWidth="copy" mobileFullWidth>Change</Button>}
                                    {!isOwnProfile && address && <Button variant={(isFollowingProfile && followHover) || isUnfollowAction ? 'primaryDanger' : isFollowingProfile ? 'subtle' : 'primary'} size="sm" minWidth="follow" onMouseEnter={() => setFollowHover(true)} onMouseLeave={() => setFollowHover(false)} disabled={isFollowInProgress} loading={isFollowInProgress} onClick={handleFollowToggle} mobileFullWidth>
                                        {isFollowInProgress ? formatStatusForPosition(myQueuePosition) || 'Processing' : isFollowingProfile ? followHover ? 'Unfollow' : 'Following' : 'Follow'}
                                    </Button>}
                                </ValueBoxWithButton>
                            </RowCentered>
                            <RowCentered>
                                <Label>Address:</Label>
                                <ValueBoxWithButton>
                                    <InlineMono title={profileAddress}>{profileAddress || '(unavailable)'}</InlineMono>
                                    {profileAddress && <Button onClick={() => {
                                        navigator.clipboard.writeText(profileAddress);
                                        setAddressCopied(true);
                                        setTimeout(() => setAddressCopied(false), 1500);
                                    }} size="sm" minWidth="copy" copied={addressCopied} mobileFullWidth>
                                        {addressCopied ? 'Copied!' : 'Copy'}
                                    </Button>}
                                </ValueBoxWithButton>
                            </RowCentered>
                            <RowCentered>
                                <Label>Tier:</Label>
                                <ValueBox>
                                    <Mono style={{
                                        color: getTierColor(userLevel)
                                    }}>
                                        {getTierName(userLevel)}
                                    </Mono>
                                    {userLevel > 0 && subscriptionExpiry > 0 && formatSubscriptionExpiry(subscriptionExpiry) && <span style={{
                                        marginLeft: '0.5rem',
                                        fontSize: '0.7rem',
                                        color: '#888'
                                    }}>
                                        ({formatSubscriptionExpiry(subscriptionExpiry)})
                                    </span>}
                                </ValueBox>
                            </RowCentered>
                            <RowCentered>
                                <HoverableLabel tabIndex={0} data-tooltip={`Spendable wallet balance in MIRAGE.\n\nThis is what a subscription will be paid with.`}>
                                    Balance:
                                </HoverableLabel>
                                <ValueBoxWithButton>
                                    <Mono>{balanceDisplay}</Mono>
                                    {!isOwnProfile && profileAddress && hasValidAccount && <Button size="sm" minWidth="copy" mobileFullWidth onClick={handleDonate} disabled={donatePending}>
                                        {donatePending ? donateStatus || 'Sending...' : 'Donate'}
                                    </Button>}
                                </ValueBoxWithButton>
                            </RowCentered>
                            {confirmDonate && <Row>
                                <div />
                                <ValueBox style={{
                                    background: 'rgba(251, 191, 36, 0.1)',
                                    borderColor: '#f59e0b'
                                }}>
                                    <div style={{
                                        display: 'flex',
                                        alignItems: 'center',
                                        gap: '0.6rem',
                                        width: '100%',
                                        flexWrap: 'wrap'
                                    }}>
                                        <span style={{
                                            whiteSpace: 'nowrap',
                                            fontSize: '0.82rem'
                                        }}>
                                            Donate to {profileUsername || profileAddress?.substring(0, 12) + '...'}:
                                        </span>
                                        <div style={{
                                            display: 'flex',
                                            alignItems: 'center',
                                            gap: '0.35rem',
                                            background: theme.colors.surface2,
                                            border: `1px solid ${theme.colors.borderSubtle}`,
                                            borderRadius: '8px',
                                            padding: '0.2rem 0.5rem'
                                        }}>
                                            <input type="text" inputMode="numeric" value={formatDonateAmount(donateAmountRaw)} onChange={e => setDonateAmountRaw(e.target.value.replace(/[^\d]/g, ""))} placeholder="10,000" maxLength={11} disabled={donatePending} style={{
                                                width: '5.5rem',
                                                background: 'transparent',
                                                border: 'none',
                                                outline: 'none',
                                                color: theme.colors.text,
                                                fontSize: '0.8rem',
                                                fontWeight: 700,
                                                textAlign: 'right'
                                            }} />
                                            <span style={{
                                                fontSize: '0.68rem',
                                                opacity: 0.7
                                            }}>MIRAGE</span>
                                        </div>
                                        <div style={{
                                            display: 'flex',
                                            gap: '0.5rem',
                                            marginLeft: 'auto',
                                            flexShrink: 0
                                        }}>
                                            <Button variant="warning" size="sm" onClick={confirmDonateAction} disabled={donatePending}>
                                                {donateStatus || 'Send'}
                                            </Button>
                                            <Button variant="ghost" size="sm" onClick={cancelDonate}>Cancel</Button>
                                        </div>
                                    </div>
                                </ValueBox>
                            </Row>}
                            {donateMessage && <Row>
                                <div />
                                <div style={{
                                    background: donateMessage.type === 'success' ? 'rgba(34, 197, 94, 0.1)' : 'rgba(239, 68, 68, 0.1)',
                                    border: donateMessage.type === 'success' ? '1px solid #22c55e' : '1px solid #ef4444',
                                    borderRadius: '8px',
                                    padding: '0.6rem 0.85rem',
                                    display: 'flex',
                                    alignItems: 'center',
                                    gap: '0.5rem',
                                    color: donateMessage.type === 'success' ? '#16a34a' : '#ef4444',
                                    fontSize: '0.8rem'
                                }}>
                                    <span>{donateMessage.type === 'success' ? '✓' : '⚠'}</span>
                                    {donateMessage.message}
                                </div>
                            </Row>}
                            <RowCentered>
                                <HoverableLabel tabIndex={0} data-tooltip={`Escrowed reserve in MIRAGE used for relayed gas and subscriptions.\n\nHeld internally by the blockchain and used to process all transactions while subscribed.\n\nNot directly spendable and will get burned if not used.`}>
                                    Reserve:
                                </HoverableLabel>
                                <ValueBox>
                                    <Mono>{reserveDisplay}</Mono>
                                </ValueBox>
                            </RowCentered>
                            <RowCentered>
                                <Label>Registered:</Label>
                                <ValueBox>
                                    <Mono>{registeredDisplay}</Mono>
                                </ValueBox>
                            </RowCentered>
                            <Row>
                                <Label>Biography:</Label>
                                <div style={{
                                    width: '100%'
                                }}>
                                    {bioEditing ? <div style={{
                                        display: 'flex',
                                        flexDirection: 'column',
                                        gap: '0.5rem'
                                    }}>
                                        <BioTextarea value={bioDraft} onChange={e => setBioDraft(e.target.value)} maxLength={BIO_MAX} rows={4} disabled={bioSaving} placeholder="Write a short biography..." autoFocus />
                                        <div style={{
                                            display: 'flex',
                                            justifyContent: 'space-between',
                                            alignItems: 'center',
                                            gap: '0.5rem',
                                            flexWrap: 'wrap'
                                        }}>
                                            <span style={{
                                                fontSize: '0.7rem',
                                                color: bioDraft.length > BIO_MAX ? '#f87171' : '#888'
                                            }}>
                                                {bioDraft.length}/{BIO_MAX}
                                            </span>
                                            <div style={{
                                                display: 'flex',
                                                gap: '0.5rem'
                                            }}>
                                                <Button size="sm" variant="subtle" disabled={bioSaving} onClick={() => {
                                                    setBioEditing(false);
                                                    setBioError('');
                                                    setBioDraft(biography);
                                                }}>
                                                    Cancel
                                                </Button>
                                                <Button size="sm" disabled={bioSaving || bioDraft.length > BIO_MAX} loading={bioSaving} onClick={handleBioSave}>
                                                    {bioButtonStatus || 'Save'}
                                                </Button>
                                            </div>
                                        </div>
                                        {bioError && <span style={{
                                            fontSize: '0.75rem',
                                            color: '#f87171'
                                        }}>{bioError}</span>}
                                    </div> : <ValueBoxWithButton>
                                        <Mono style={{
                                            whiteSpace: 'pre-wrap',
                                            wordBreak: 'break-word',
                                            color: biography ? undefined : '#888',
                                            fontSize: '0.8rem'
                                        }}>
                                            {biography || (isOwnProfile ? 'No biography set.' : 'No biography.')}
                                        </Mono>
                                        {isOwnProfile && canHaveBiography && <Button size="sm" minWidth="copy" mobileFullWidth onClick={() => {
                                            setBioDraft(biography);
                                            setBioEditing(true);
                                            setBioError('');
                                        }}>
                                            {biography ? 'Edit' : 'Add'}
                                        </Button>}
                                        {isOwnProfile && !canHaveBiography && <Button size="sm" variant="subtle" mobileFullWidth onClick={() => navigate('/subscription')}>
                                            Upgrade
                                        </Button>}
                                    </ValueBoxWithButton>}
                                </div>
                            </Row>
                        </>}

                        {isPostsTab && profileUsesListFeed && <>
                            {isLoadingRecentPosts && recentPosts.length === 0 && <LoadingRow>
                                <LoadingSpinner />
                                <SubtleMono>Loading posts...</SubtleMono>
                            </LoadingRow>}
                            {!isLoadingRecentPosts && recentPostsError && <Mono style={{
                                color: '#f87171'
                            }}>{recentPostsError}</Mono>}
                            {!isLoadingRecentPosts && !recentPostsError && recentPosts.length === 0 && <SubtleMono>No {effectivePostsFilter === 'all' ? 'posts' : effectivePostsFilter === 'submissions' ? 'submissions' : 'comments'} yet.</SubtleMono>}
                            {recentPosts.length > 0 && <FeedComponent posts={recentPosts} state={state} showSortTabs={false} />}
                            {(recentAutoLoading || (isLoadingRecentPosts && recentPage > 1)) && <SubtleMono style={{
                                display: 'block',
                                marginTop: '0.5rem',
                                fontStyle: 'italic'
                            }}>
                                Loading more...
                            </SubtleMono>}
                            <div ref={recentBottomSentinelRef} style={{
                                width: '100%',
                                height: '20px',
                                minHeight: '20px'
                            }} />
                        </>}

                        {isPostsTab && !profileUsesListFeed && <>
                            {!profileHideFilterSelect && profileAddress && <FilterSelect value={recentPostsFilter} onChange={e => setRecentPostsFilter(e.target.value)}>
                                <option value="all">All</option>
                                <option value="submissions">Submissions</option>
                                <option value="comments">Comments</option>
                            </FilterSelect>}
                            {isLoadingRecentPosts && <LoadingRow>
                                <LoadingSpinner />
                                <SubtleMono>Loading posts...</SubtleMono>
                            </LoadingRow>}
                            {!isLoadingRecentPosts && recentPostsError && <Mono style={{
                                color: '#f87171'
                            }}>{recentPostsError}</Mono>}
                            {!isLoadingRecentPosts && !recentPostsError && recentPosts.length === 0 && <SubtleMono>No {effectivePostsFilter === 'all' ? 'posts' : effectivePostsFilter === 'submissions' ? 'submissions' : 'comments'} yet.</SubtleMono>}
                            {!recentPostsError && recentPosts.length > 0 && <PostsList>
                                {recentPosts.map(post => <PostItem key={post.post_id} href={getPostUrl(post)} isActive={activeRecentPost === post.post_id} onClick={e => handleRecentPostClick(post, e)}>
                                    <PostPreview>{renderPostPreview(post)}</PostPreview>
                                    <PostMeta>{buildMetaLine(post)}</PostMeta>
                                </PostItem>)}
                            </PostsList>}
                            {(recentAutoLoading || (isLoadingRecentPosts && recentPage > 1)) && <SubtleMono style={{
                                display: 'block',
                                marginTop: '0.5rem',
                                fontStyle: 'italic'
                            }}>
                                Loading more...
                            </SubtleMono>}
                            <div ref={recentBottomSentinelRef} style={{
                                width: '100%',
                                height: '20px',
                                minHeight: '20px'
                            }} />
                        </>}

                        {activeTab === 'algo' && <>
                            <SectionTitle $first>Topic preferences</SectionTitle>
                            <ValueBox style={{
                                padding: '0.25rem 0.5rem'
                            }}>
                                {prefsLoading && <Mono style={{
                                    color: '#888'
                                }}>Loading...</Mono>}
                                {!prefsLoading && prefsError && <Mono style={{
                                    color: '#f87171'
                                }}>{prefsError}</Mono>}
                                {!prefsLoading && !prefsError && prefsTopics.length === 0 && <Mono style={{
                                    color: '#888'
                                }}>No topic preference data yet.</Mono>}
                                {!prefsError && prefsTopics.length > 0 && <div>
                                    {(() => {
                                        const CAP = 5;
                                        const needsCollapse = prefsTopics.length > CAP * 2;
                                        const visible = needsCollapse && !showAllTopicPrefs ? [...prefsTopics.slice(0, CAP), null, ...prefsTopics.slice(-CAP)] : prefsTopics;
                                        return visible.map((t, i) => {
                                            if (t === null) {
                                                const hidden = prefsTopics.length - CAP * 2;
                                                return <div key="__expand" style={{
                                                    textAlign: 'center',
                                                    padding: '4px 0'
                                                }}>
                                                    <Mono onClick={() => setShowAllTopicPrefs(true)} style={{
                                                        cursor: 'pointer',
                                                        color: '#888',
                                                        fontStyle: 'italic',
                                                        fontSize: '0.6rem'
                                                    }}>
                                                        show {hidden} more...
                                                    </Mono>
                                                </div>;
                                            }
                                            return <div key={t.topic} style={{
                                                display: 'flex',
                                                justifyContent: 'space-between',
                                                padding: '4px 0'
                                            }}>
                                                <a href={`/t/${encodeURIComponent(t.topic)}`} onClick={e => {
                                                    if (e.button === 0 && !e.metaKey && !e.ctrlKey && !e.shiftKey) {
                                                        e.preventDefault();
                                                        navigate(`/t/${encodeURIComponent(t.topic)}`);
                                                    }
                                                }} style={{
                                                    textDecoration: 'none',
                                                    color: 'inherit'
                                                }}><Mono style={{
                                                    cursor: 'pointer'
                                                }}>#{t.topic}</Mono></a>
                                                <Mono style={{
                                                    color: colorForWeight(t.weight)
                                                }}>
                                                    {formatPrefWeight(t.weight)}
                                                </Mono>
                                            </div>;
                                        });
                                    })()}
                                    {showAllTopicPrefs && prefsTopics.length > 10 && <div style={{
                                        textAlign: 'center',
                                        padding: '4px 0'
                                    }}>
                                        <Mono onClick={() => setShowAllTopicPrefs(false)} style={{
                                            cursor: 'pointer',
                                            color: '#888',
                                            fontStyle: 'italic',
                                            fontSize: '0.6rem'
                                        }}>
                                            show less
                                        </Mono>
                                    </div>}
                                </div>}
                            </ValueBox>

                            <SectionTitle>User preferences</SectionTitle>
                            <ValueBox style={{
                                padding: '0.25rem 0.5rem'
                            }}>
                                {prefsLoading && <Mono style={{
                                    color: '#888'
                                }}>Loading...</Mono>}
                                {!prefsLoading && prefsError && <Mono style={{
                                    color: '#f87171'
                                }}>{prefsError}</Mono>}
                                {!prefsLoading && !prefsError && prefsAuthors.length === 0 && <Mono style={{
                                    color: '#888'
                                }}>No user preference data yet.</Mono>}
                                {!prefsError && prefsAuthors.length > 0 && <div>
                                    {(() => {
                                        const CAP = 5;
                                        const needsCollapse = prefsAuthors.length > CAP * 2;
                                        const visible = needsCollapse && !showAllAuthorPrefs ? [...prefsAuthors.slice(0, CAP), null, ...prefsAuthors.slice(-CAP)] : prefsAuthors;
                                        return visible.map((u, i) => {
                                            if (u === null) {
                                                const hidden = prefsAuthors.length - CAP * 2;
                                                return <div key="__expand" style={{
                                                    textAlign: 'center',
                                                    padding: '4px 0'
                                                }}>
                                                    <Mono onClick={() => setShowAllAuthorPrefs(true)} style={{
                                                        cursor: 'pointer',
                                                        color: '#888',
                                                        fontStyle: 'italic',
                                                        fontSize: '0.6rem'
                                                    }}>
                                                        show {hidden} more...
                                                    </Mono>
                                                </div>;
                                            }
                                            const uname = prefAuthorUsernames[String(u.user || '').toLowerCase()];
                                            return <a key={u.user} href={`/u/${encodeURIComponent(prefAuthorUsernames[u.user] || u.user)}?tab=posts`} onClick={e => {
                                                if (e.button === 0 && !e.metaKey && !e.ctrlKey && !e.shiftKey) {
                                                    e.preventDefault();
                                                    navigate(`/u/${encodeURIComponent(prefAuthorUsernames[u.user] || u.user)}?tab=posts`);
                                                }
                                            }} style={{
                                                display: 'flex',
                                                justifyContent: 'space-between',
                                                padding: '4px 0',
                                                cursor: 'pointer',
                                                textDecoration: 'none',
                                                color: 'inherit'
                                            }}>
                                                <Mono>{uname && uname !== u.user ? uname : shortenAddress(u.user)}</Mono>
                                                <Mono style={{
                                                    color: colorForWeight(u.weight)
                                                }}>
                                                    {formatPrefWeight(u.weight)}
                                                </Mono>
                                            </a>;
                                        });
                                    })()}
                                    {showAllAuthorPrefs && prefsAuthors.length > 10 && <div style={{
                                        textAlign: 'center',
                                        padding: '4px 0'
                                    }}>
                                        <Mono onClick={() => setShowAllAuthorPrefs(false)} style={{
                                            cursor: 'pointer',
                                            color: '#888',
                                            fontStyle: 'italic',
                                            fontSize: '0.6rem'
                                        }}>
                                            show less
                                        </Mono>
                                    </div>}
                                </div>}
                            </ValueBox>

                            <SectionTitle>Similar users</SectionTitle>
                            <ValueBox style={{
                                padding: '0.25rem 0.5rem'
                            }}>
                                {similarUsersLoading && <Mono style={{
                                    color: '#888'
                                }}>Computing similarity...</Mono>}
                                {!similarUsersLoading && similarUsersError && <Mono style={{
                                    color: '#f87171'
                                }}>{similarUsersError}</Mono>}
                                {!similarUsersLoading && !similarUsersError && similarUsers.length === 0 && <Mono style={{
                                    color: '#888'
                                }}>No similar users found yet.</Mono>}
                                {!similarUsersError && similarUsers.length > 0 && <div>
                                    {(showAllSimilarUsers ? similarUsers : similarUsers.slice(0, 5)).map(u => <a key={u.address} href={`/u/${encodeURIComponent(u.username || u.address)}?tab=posts`} onClick={e => {
                                        if (e.button === 0 && !e.metaKey && !e.ctrlKey && !e.shiftKey) {
                                            e.preventDefault();
                                            navigate(`/u/${encodeURIComponent(u.username || u.address)}?tab=posts`);
                                        }
                                    }} style={{
                                        display: 'flex',
                                        justifyContent: 'space-between',
                                        padding: '4px 0',
                                        cursor: 'pointer',
                                        textDecoration: 'none',
                                        color: 'inherit'
                                    }}>
                                        <Mono>{u.username || shortenAddress(u.address)}</Mono>
                                        <Mono style={{
                                            color: u.similarity >= 0 ? '#22c55e' : '#ef4444'
                                        }}>
                                            {u.similarity >= 0 ? '+' : ''}{Math.round(u.similarity * 100)}% ({u.shared_dimensions} shared)
                                        </Mono>
                                    </a>)}
                                    {!showAllSimilarUsers && similarUsers.length > 5 && <div style={{
                                        textAlign: 'center',
                                        padding: '4px 0'
                                    }}>
                                        <Mono onClick={() => setShowAllSimilarUsers(true)} style={{
                                            cursor: 'pointer',
                                            color: '#888',
                                            fontStyle: 'italic',
                                            fontSize: '0.6rem'
                                        }}>
                                            show {similarUsers.length - 5} more...
                                        </Mono>
                                    </div>}
                                    {showAllSimilarUsers && similarUsers.length > 5 && <div style={{
                                        textAlign: 'center',
                                        padding: '4px 0'
                                    }}>
                                        <Mono onClick={() => setShowAllSimilarUsers(false)} style={{
                                            cursor: 'pointer',
                                            color: '#888',
                                            fontStyle: 'italic',
                                            fontSize: '0.6rem'
                                        }}>
                                            show less
                                        </Mono>
                                    </div>}
                                </div>}
                            </ValueBox>
                        </>}

                    </ContainerBody>
                </TabbedContainer>
            </ModernPostFeed>
        </div>
    </ContentGrid>;
}