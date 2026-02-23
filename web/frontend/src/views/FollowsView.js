import React, { useEffect, useState } from "react";
import { Helmet } from 'react-helmet-async';
import styled from "styled-components";
import { useNavigate, useLocation } from 'react-router-dom';
import Storage from "../utils/Storage";
import seedVault from "../utils/SeedVault";
import { derivePrivateKeyFromSeed, derivePublicKeyFromSeed } from "../utils/CryptoUtils";
import Api from '../lib/api';
import * as tx from '../utils/tx';
import Sidebar from "../components/Sidebar";
import TopBar from "../components/TopBar";
import Button from "../components/Button";
import MobileHeader from "../components/MobileHeader";
import { ContentGrid, ModernPostFeed, TabbedContainer, ContainerBody, TabsRow, ClickableTab } from "../styled/Layout";
import { unfollow, notifyUsersUpdated } from "../utils/FollowUsers";
import { notifyTopicsUpdated } from "../utils/Subscriptions";
import { usePendingFollows } from "../utils/useFollowState";
import { resolveUsernames as resolveUsernamesCached } from "../utils/UsernameCache";

const SectionTitle = styled.div`
    margin-top: ${({ $first }) => $first ? '0' : '1.5rem'};
    margin-bottom: 0.5rem;
    font-weight: 700;
    color: ${({ theme }) => theme?.colors?.text || '#FFFFFF'};
    font-size: 0.95rem;
    display: flex;
    align-items: center;
    gap: 0.5rem;

    &::after {
        content: '';
        flex: 1;
        height: 1px;
        background: ${({ theme }) => theme?.colors?.border || '#333'};
    }
`;

const ValueBox = styled.div`
    background-color: ${({ theme }) => theme?.colors?.panelAlt || '#1f2328'};
    border: 1px solid ${({ theme }) => theme?.colors?.border || '#444'};
    border-radius: 8px;
    padding: 0.6rem 0.85rem;
    width: 100%;
    box-sizing: border-box;
    overflow-x: auto;
`;

const PostsList = styled.div`
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
`;

const PostItem = styled.div`
    border: 1px solid ${({ theme }) => theme?.colors?.border || '#444'};
    background-color: ${({ theme }) => theme?.colors?.panel || '#23272C'};
    border-radius: 8px;
    padding: 0.6rem 0.85rem;
    cursor: pointer;
    transition: background-color 0.2s ease, border-color 0.2s ease;

    &:hover {
        background-color: ${({ theme }) => theme?.colors?.panelAlt || '#2E3238'};
        border-color: ${({ theme }) => theme?.colors?.subtleText || '#666'};
    }
`;

const BlockItemRow = styled.div`
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.75rem;
`;

const BlockItemContent = styled.div`
    min-width: 0;
    flex: 1;
`;

const BlockItemActions = styled.div`
    flex-shrink: 0;
    display: flex;
    align-items: center;
`;

const PostMeta = styled.div`
    font-size: 0.55rem;
    color: ${({ theme }) => theme?.colors?.subtleText || '#CCCCCC'};
    margin-bottom: 0.25rem;
    display: flex;
    flex-wrap: wrap;
    gap: 0.35rem;
`;

const PostPreview = styled.div`
    font-size: 0.65rem;
    color: ${({ theme }) => theme?.colors?.text || '#DDDDDD'};
    line-height: 1.3;
    word-break: break-word;
    white-space: pre-line;
`;

const Mono = styled.span`
    color: ${({ theme }) => theme?.colors?.text || '#eee'};
    font-size: 0.8rem;
    font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
    white-space: normal;
    word-break: break-word;
    overflow-wrap: anywhere;
`;

const ModeratorsList = styled.div`
    display: flex;
    flex-wrap: wrap;
    gap: 0.5rem;
    margin-bottom: 0.5rem;
`;

const ModeratorTag = styled.div`
    background-color: ${({ theme }) => theme?.colors?.accent || '#2E3238'};
    border: 1px solid ${({ theme }) => theme?.colors?.border || '#444'};
    border-radius: 20px;
    padding: 0.35rem 0.75rem;
    display: flex;
    align-items: center;
    gap: 0.4rem;
    font-size: 0.8rem;
    color: ${({ theme }) => theme?.colors?.text || '#eee'};
    opacity: ${({ $isRemoving }) => $isRemoving ? 0.5 : 1};
    transition: opacity 0.2s ease;
`;

const RemoveModeratorButton = styled.button`
    background: none;
    border: none;
    color: ${({ theme }) => theme?.colors?.subtleText || '#ccc'};
    cursor: pointer;
    padding: 0;
    font-size: 0.9rem;
    line-height: 1;
    
    &:hover {
        color: ${({ theme }) => theme?.colors?.text || '#fff'};
    }
`;

const ModeratorInput = styled.input`
    background-color: ${({ theme }) => theme?.colors?.panelAlt || '#1f2328'};
    border: 1px solid ${({ theme }) => theme?.colors?.border || '#444'};
    border-radius: 8px;
    padding: 0.5rem 0.85rem;
    color: ${({ theme }) => theme?.colors?.text || '#eee'};
    font-size: 0.85rem;
    flex: 1;
    transition: all 0.2s ease;
    
    &:focus {
        outline: none;
        border-color: #667eea;
        box-shadow: 0 0 0 3px rgba(102, 126, 234, 0.15);
    }
`;

const ModeratorInputRow = styled.div`
    display: flex;
    margin-top: 0.5rem;
    align-items: center;
    gap: 0.5rem;
    @media (max-width: 600px) {
        flex-direction: column;
        align-items: stretch;
    }
`;

const ModeratorErrorMessage = styled.div`
    background-color: rgba(220, 38, 38, 0.1);
    border: 1px solid #dc2626;
    border-radius: 3px;
    padding: 0.5rem;
    margin-top: 0.5rem;
    color: #dc2626;
    font-size: 0.8rem;
    display: flex;
    align-items: center;
    gap: 0.5rem;
`;

const ModeratorSuccessMessage = styled.div`
    background-color: rgba(34, 197, 94, 0.1);
    border: 1px solid #22c55e;
    border-radius: 3px;
    padding: 0.5rem;
    margin-top: 0.5rem;
    color: #22c55e;
    font-size: 0.8rem;
    display: flex;
    align-items: center;
    gap: 0.5rem;
`;

const LoadingSpinner = styled.div`
    width: 16px;
    height: 16px;
    border: 2px solid ${({ theme }) => theme?.colors?.border || theme?.colors?.borderSubtle || '#393E46'};
    border-top: 2px solid ${({ theme }) => theme?.colors?.subtleText || '#bcb1a2'};
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
    
    @keyframes spin {
        0% { transform: rotate(0deg); }
        100% { transform: rotate(360deg); }
    }
`;

const shortenAddress = (addr) => {
    if (!addr) return '';
    if (addr.length <= 24) return addr;
    return `${addr.slice(0, 14)}...${addr.slice(-8)}`;
};

export default function FollowsView({ state }) {
    const navigate = useNavigate();
    const location = useLocation();
    const address = (state && state.publicKey) ? state.publicKey : Storage.load('publicKey', '');
    const seedPhrase = (state && state.seedPhrase) ? state.seedPhrase : (seedVault.getSeed() || '');

    const [followedUsers, setFollowedUsers] = useState([]);
    const [followedTopics, setFollowedTopics] = useState([]);
    const [moderators, setModerators] = useState([]);
    const [moderatorUsernames, setModeratorUsernames] = useState({});
    const [followedUsernames, setFollowedUsernames] = useState({});
    const [listsLoading, setListsLoading] = useState(false);
    const [listsError, setListsError] = useState('');
    const [newModeratorInput, setNewModeratorInput] = useState('');
    const [moderatorError, setModeratorError] = useState('');
    const [moderatorSuccess, setModeratorSuccess] = useState('');
    const [isAddingModerator, setIsAddingModerator] = useState(false);
    const [isRemovingModerator, setIsRemovingModerator] = useState('');

    const {
        isTopicPending: isFollowTopicPending,
        isUserPending: isFollowUserPending,
        formatTopicStatus: formatFollowTopicStatus,
        formatUserStatus: formatFollowUserStatus,
    } = usePendingFollows();

    useEffect(() => {
        if (!address) return;
        let cancelled = false;
        const fetchFollows = async () => {
            setListsLoading(true);
            setListsError('');
            try {
                const data = await Api.get('get_user_followed', { address });
                if (cancelled) return;
                setFollowedUsers(data?.followed_users || []);
                setFollowedTopics(data?.followed_topics || []);
                setModerators(data?.followed_moderators || []);
                Storage.save('followed_moderators', data?.followed_moderators || []);
            } catch (err) {
                if (!cancelled) {
                    setListsError(err?.message || 'Failed to load follows');
                }
            } finally {
                if (!cancelled) {
                    setListsLoading(false);
                }
            }
        };
        fetchFollows();
        return () => { cancelled = true; };
    }, [address]);

    useEffect(() => {
        const combined = [...moderators, ...followedUsers]
            .map(a => String(a || '').trim())
            .filter(Boolean);
        if (combined.length === 0) {
            setModeratorUsernames({});
            setFollowedUsernames({});
            return;
        }

        let cancelled = false;
        const resolveAll = async () => {
            try {
                const mapping = await resolveUsernamesCached(combined, { timeoutMs: 5000 });
                if (cancelled) return;
                const buildMap = (addresses) => {
                    const result = {};
                    for (const addr of addresses) {
                        const lower = String(addr || '').toLowerCase();
                        const uname = mapping[lower];
                        result[addr] = uname || addr;
                    }
                    return result;
                };
                setModeratorUsernames(buildMap(moderators));
                setFollowedUsernames(buildMap(followedUsers));
            } catch {
                if (cancelled) return;
                const buildFallback = (addresses) => {
                    const result = {};
                    addresses.forEach(a => { result[a] = a; });
                    return result;
                };
                setModeratorUsernames(buildFallback(moderators));
                setFollowedUsernames(buildFallback(followedUsers));
            }
        };
        resolveAll();
        return () => { cancelled = true; };
    }, [moderators, followedUsers]);

    const clearMessages = () => {
        setModeratorError('');
        setModeratorSuccess('');
    };

    const showError = (message) => {
        setModeratorError(message);
        setModeratorSuccess('');
        setTimeout(() => setModeratorError(''), 5000);
    };

    const showSuccess = (message) => {
        setModeratorSuccess(message);
        setModeratorError('');
        setTimeout(() => setModeratorSuccess(''), 3000);
    };

    const addModerator = async () => {
        const trimmed = newModeratorInput.trim();
        if (!trimmed) return;

        clearMessages();
        setIsAddingModerator(true);

        if (!/^[A-Za-z0-9-]+$/.test(trimmed)) {
            showError('Invalid username format. Only letters, numbers, and hyphens are allowed.');
            setIsAddingModerator(false);
            return;
        }

        try {
            const response = await Api.get('get_address_from_username', { username: trimmed }, { timeoutMs: 5000 });
            if (!response || !response.exists || !response.address) {
                showError(`Username "${trimmed}" not found. Make sure the username exists on-chain.`);
                setIsAddingModerator(false);
                return;
            }

            const modAddress = response.address;

            if (moderators.map(m => m.toLowerCase()).includes(modAddress.toLowerCase())) {
                showError('This moderator is already in your list.');
                setIsAddingModerator(false);
                return;
            }

            const paramsData = await Api.get('get_parameters', address ? { address } : undefined, { timeoutMs: 5000 });
            if (!paramsData) {
                showError('Unable to fetch network parameters. Please try again.');
                setIsAddingModerator(false);
                return;
            }

            const lastBlockHash = paramsData.last_block_hash || '';
            const powDifficulty = Number(paramsData.pow_difficulty);

            if (!lastBlockHash) {
                showError('Unable to get last block hash from server. Please try again.');
                setIsAddingModerator(false);
                return;
            }

            if (!seedPhrase) {
                showError('Seed phrase not available. Please sign in again.');
                setIsAddingModerator(false);
                return;
            }

            const transaction = {
                action: 'follow_moderator',
                moderator: modAddress,
                last_block_hash: lastBlockHash,
                pow_difficulty: powDifficulty,
                difficulty: powDifficulty,
            };

            const result = await tx.performTransaction(
                transaction,
                lastBlockHash,
                derivePrivateKeyFromSeed(seedPhrase),
                address,
                false
            );

            if (result.success) {
                const updated = [...moderators.filter(m => m !== modAddress), modAddress];
                if (updated.length > 3) updated.shift();
                setModerators(updated);
                Storage.save('followed_moderators', updated);
                setNewModeratorInput('');
                showSuccess(`Successfully added moderator "${trimmed}"`);
            } else {
                showError(`Failed to add moderator: ${result.error || 'Unknown error'}`);
            }
        } catch (error) {
            showError(`Error checking username: ${error.message || 'Network error'}`);
        } finally {
            setIsAddingModerator(false);
        }
    };

    const removeModerator = async (modAddress) => {
        setIsRemovingModerator(modAddress);
        clearMessages();

        try {
            const updated = moderators.filter(m => m !== modAddress);

            const paramsData = await Api.get('get_parameters', address ? { address } : undefined, { timeoutMs: 5000 });
            if (!paramsData) {
                showError('Unable to fetch network parameters. Please try again.');
                setIsRemovingModerator('');
                return;
            }

            const lastBlockHash = paramsData.last_block_hash || '';
            const powDifficulty = Number(paramsData.pow_difficulty);

            if (!lastBlockHash) {
                showError('Unable to fetch last block hash. Please try again.');
                setIsRemovingModerator('');
                return;
            }

            const currentSeed = seedVault.getSeed() || '';
            if (!currentSeed) {
                showError('No seed phrase found. Please sign in again.');
                setIsRemovingModerator('');
                return;
            }

            const transaction = {
                action: 'unfollow_moderator',
                moderator: modAddress,
                last_block_hash: lastBlockHash,
                pow_difficulty: powDifficulty >>> 0,
            };

            const privateKeyHex = derivePrivateKeyFromSeed(currentSeed);
            const derivedAddress = derivePublicKeyFromSeed(currentSeed);
            const challenge = `${derivedAddress}:${lastBlockHash}:${powDifficulty}`;

            const result = await tx.performTransaction(transaction, challenge, privateKeyHex, derivedAddress, false);

            if (result && result.success) {
                setModerators(updated);
                Storage.save('followed_moderators', updated);
                const uname = moderatorUsernames[modAddress] || modAddress;
                showSuccess(`Removed moderator "${uname}"`);
            } else {
                showError(`Failed to remove moderator: ${result?.error || 'Unknown error'}`);
            }
        } catch (error) {
            console.error('Remove moderator error:', error);
            showError(`Failed to remove moderator: ${error.message || error}`);
        } finally {
            setIsRemovingModerator('');
        }
    };

    const handleModeratorKeyDown = (e) => {
        if (e.key === 'Enter') {
            e.preventDefault();
            addModerator();
        }
    };

    const handleUnfollowTopic = async (e, topic) => {
        if (e && typeof e.stopPropagation === 'function') e.stopPropagation();
        const topicTrimmed = String(topic || '').trim().toLowerCase();
        if (!topicTrimmed) return;
        try {
            const result = await tx.unfollowTopic(topicTrimmed);
            if (result && result.success) {
                setFollowedTopics((prev) => prev.filter(t => String(t || '').trim().toLowerCase() !== topicTrimmed));
                notifyTopicsUpdated({ removed: topicTrimmed });
            } else {
                alert(`Failed to unfollow topic: ${result?.error || 'Unknown error'}`);
            }
        } catch (error) {
            alert(`Error unfollowing topic: ${error?.message || error}`);
        }
    };

    const handleUnfollowUser = async (e, userAddr) => {
        if (e && typeof e.stopPropagation === 'function') e.stopPropagation();
        const userTrimmed = String(userAddr || '').trim().toLowerCase();
        if (!userTrimmed) return;
        try {
            await unfollow(address, userTrimmed);
            setFollowedUsers((prev) => prev.filter(u => String(u || '').trim().toLowerCase() !== userTrimmed));
            notifyUsersUpdated({ removed: userTrimmed });
        } catch (error) {
            alert(`Error unfollowing user: ${error?.message || error}`);
        }
    };

    return (
        <ContentGrid>
            <Helmet>
                <title>Follows | Mirage</title>
            </Helmet>
            <Sidebar currentPath={location.pathname} state={state} />
            <div>
                <TopBar state={state} />
                <ModernPostFeed>
                    <MobileHeader />
                    <TabbedContainer>
                        <TabsRow>
                            <ClickableTab $active>Follows</ClickableTab>
                        </TabsRow>
                        <ContainerBody>
                            <SectionTitle $first>Moderators</SectionTitle>
                            <ValueBox>
                                {listsLoading && <Mono style={{ color: '#888' }}>Loading...</Mono>}
                                {!listsLoading && !listsError && moderators.length === 0 && (
                                    <Mono style={{ color: '#888' }}>No moderators set. Add up to 3 moderators whose block lists will be applied to your feed.</Mono>
                                )}
                                {!listsLoading && !listsError && moderators.length > 0 && (
                                    <ModeratorsList>
                                        {moderators.map((modAddr) => (
                                            <ModeratorTag key={modAddr} $isRemoving={isRemovingModerator === modAddr}>
                                                <Mono
                                                    style={{ cursor: 'pointer' }}
                                                    onClick={() => navigate(`/u/${encodeURIComponent(moderatorUsernames[modAddr] || modAddr)}?tab=posts`)}
                                                >
                                                    {moderatorUsernames[modAddr] && moderatorUsernames[modAddr] !== modAddr
                                                        ? moderatorUsernames[modAddr]
                                                        : shortenAddress(modAddr)}
                                                </Mono>
                                                <RemoveModeratorButton
                                                    onClick={() => removeModerator(modAddr)}
                                                    title="Remove"
                                                    disabled={isRemovingModerator === modAddr}
                                                >
                                                    {isRemovingModerator === modAddr ? <LoadingSpinner /> : '×'}
                                                </RemoveModeratorButton>
                                            </ModeratorTag>
                                        ))}
                                    </ModeratorsList>
                                )}
                                {!listsLoading && (
                                    <>
                                        <ModeratorInputRow>
                                            <ModeratorInput
                                                type="text"
                                                placeholder="Add a moderator by username"
                                                value={newModeratorInput}
                                                onChange={(e) => {
                                                    setNewModeratorInput(e.target.value);
                                                    setModeratorError('');
                                                    setModeratorSuccess('');
                                                }}
                                                onKeyDown={handleModeratorKeyDown}
                                                disabled={isAddingModerator}
                                            />
                                            <Button
                                                onClick={addModerator}
                                                disabled={isAddingModerator || !newModeratorInput.trim()}
                                                loading={isAddingModerator}
                                                size="sm"
                                            >
                                                Add
                                            </Button>
                                        </ModeratorInputRow>
                                        {moderatorError && (
                                            <ModeratorErrorMessage>
                                                <span>⚠</span>
                                                {moderatorError}
                                            </ModeratorErrorMessage>
                                        )}
                                        {moderatorSuccess && (
                                            <ModeratorSuccessMessage>
                                                <span>✓</span>
                                                {moderatorSuccess}
                                            </ModeratorSuccessMessage>
                                        )}
                                    </>
                                )}
                            </ValueBox>

                            <SectionTitle>Topics</SectionTitle>
                            <ValueBox>
                                {listsLoading && <Mono style={{ color: '#888' }}>Loading...</Mono>}
                                {!listsLoading && !listsError && followedTopics.length === 0 && (
                                    <Mono style={{ color: '#888' }}>Not following any topics.</Mono>
                                )}
                                {!listsLoading && !listsError && followedTopics.length > 0 && (
                                    <PostsList>
                                        {followedTopics.map((topic) => {
                                            const isPending = isFollowTopicPending(topic);
                                            const status = formatFollowTopicStatus(topic);
                                            return (
                                                <PostItem key={topic} onClick={() => navigate(`/t/${encodeURIComponent(topic)}`)}>
                                                    <BlockItemRow>
                                                        <BlockItemContent>
                                                            <PostPreview>#{topic}</PostPreview>
                                                        </BlockItemContent>
                                                        <BlockItemActions>
                                                            <Button
                                                                variant="ghost"
                                                                size="sm"
                                                                disabled={isPending}
                                                                loading={isPending}
                                                                onClick={(e) => handleUnfollowTopic(e, topic)}
                                                            >
                                                                {status || 'Unfollow'}
                                                            </Button>
                                                        </BlockItemActions>
                                                    </BlockItemRow>
                                                </PostItem>
                                            );
                                        })}
                                    </PostsList>
                                )}
                            </ValueBox>

                            <SectionTitle>Users</SectionTitle>
                            <ValueBox>
                                {listsLoading && <Mono style={{ color: '#888' }}>Loading...</Mono>}
                                {!listsLoading && listsError && <Mono style={{ color: '#f87171' }}>{listsError}</Mono>}
                                {!listsLoading && !listsError && followedUsers.length === 0 && (
                                    <Mono style={{ color: '#888' }}>Not following any users.</Mono>
                                )}
                                {!listsLoading && !listsError && followedUsers.length > 0 && (
                                    <PostsList>
                                        {followedUsers.map((userAddr) => {
                                            const isPending = isFollowUserPending(userAddr);
                                            const status = formatFollowUserStatus(userAddr);
                                            return (
                                                <PostItem
                                                    key={userAddr}
                                                    onClick={() => navigate(`/u/${encodeURIComponent(followedUsernames[userAddr] || userAddr)}?tab=posts`)}
                                                >
                                                    <BlockItemRow>
                                                        <BlockItemContent>
                                                            <PostPreview>
                                                                {followedUsernames[userAddr] && followedUsernames[userAddr] !== userAddr
                                                                    ? followedUsernames[userAddr]
                                                                    : shortenAddress(userAddr)}
                                                            </PostPreview>
                                                            <PostMeta>{userAddr}</PostMeta>
                                                        </BlockItemContent>
                                                        <BlockItemActions>
                                                            <Button
                                                                variant="ghost"
                                                                size="sm"
                                                                disabled={isPending}
                                                                loading={isPending}
                                                                onClick={(e) => handleUnfollowUser(e, userAddr)}
                                                            >
                                                                {status || 'Unfollow'}
                                                            </Button>
                                                        </BlockItemActions>
                                                    </BlockItemRow>
                                                </PostItem>
                                            );
                                        })}
                                    </PostsList>
                                )}
                            </ValueBox>
                        </ContainerBody>
                    </TabbedContainer>
                </ModernPostFeed>
            </div>
        </ContentGrid>
    );
}
