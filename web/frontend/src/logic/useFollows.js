import { useEffect, useState } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import Storage from "../utils/Storage";
import Api from "../utils/api";
import * as tx from "../utils/tx";
import { unfollow, notifyUsersUpdated } from "../utils/FollowUsers";
import { notifyTopicsUpdated } from "../utils/Subscriptions";
import { usePendingFollows } from "./useFollowState.js";
import { resolveUsernames as resolveUsernamesCached } from "../utils/UsernameCache";
export const shortenAddress = addr => {
  if (!addr) return '';
  if (addr.length <= 24) return addr;
  return `${addr.slice(0, 14)}...${addr.slice(-8)}`;
};
export function useFollows({
  state
}) {
  const navigate = useNavigate();
  const location = useLocation();
  const address = state && state.publicKey ? state.publicKey : Storage.load('publicKey', '');
  const [followedUsers, setFollowedUsers] = useState([]);
  const [followedTopics, setFollowedTopics] = useState([]);
  const [followedUsernames, setFollowedUsernames] = useState({});
  const [listsLoading, setListsLoading] = useState(false);
  const [listsError, setListsError] = useState('');
  const {
    isTopicPending: isFollowTopicPending,
    isUserPending: isFollowUserPending,
    formatTopicStatus: formatFollowTopicStatus,
    formatUserStatus: formatFollowUserStatus
  } = usePendingFollows();
  useEffect(() => {
    if (!address) return;
    let cancelled = false;
    const fetchFollows = async () => {
      setListsLoading(true);
      setListsError('');
      try {
        const data = await Api.get('get_user_followed', {
          address
        });
        if (cancelled) return;
        setFollowedUsers(data?.followed_users || []);
        setFollowedTopics(data?.joined_communities || []);
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
    return () => {
      cancelled = true;
    };
  }, [address]);
  useEffect(() => {
    const addresses = followedUsers.map(a => String(a || '').trim()).filter(Boolean);
    if (addresses.length === 0) {
      setFollowedUsernames({});
      return;
    }
    let cancelled = false;
    const resolveAll = async () => {
      try {
        const mapping = await resolveUsernamesCached(addresses, {
          timeoutMs: 5000
        });
        if (cancelled) return;
        const result = {};
        for (const addr of addresses) {
          const lower = String(addr || '').toLowerCase();
          const uname = mapping[lower];
          result[addr] = uname || addr;
        }
        setFollowedUsernames(result);
      } catch {
        if (cancelled) return;
        const result = {};
        addresses.forEach(a => {
          result[a] = a;
        });
        setFollowedUsernames(result);
      }
    };
    resolveAll();
    return () => {
      cancelled = true;
    };
  }, [followedUsers]);
  const handleUnfollowTopic = async (e, topic) => {
    if (e && typeof e.stopPropagation === 'function') e.stopPropagation();
    const topicTrimmed = String(topic || '').trim().toLowerCase();
    if (!topicTrimmed) return;
    try {
      const result = await tx.unfollowTopic(topicTrimmed);
      if (result && result.success) {
        setFollowedTopics(prev => prev.filter(t => String(t || '').trim().toLowerCase() !== topicTrimmed));
        notifyTopicsUpdated({
          removed: topicTrimmed
        });
      } else {
        alert(`Failed to unfollow community: ${result?.error || 'Unknown error'}`);
      }
    } catch (error) {
      alert(`Error unfollowing community: ${error?.message || error}`);
    }
  };
  const handleUnfollowUser = async (e, userAddr) => {
    if (e && typeof e.stopPropagation === 'function') e.stopPropagation();
    const userTrimmed = String(userAddr || '').trim().toLowerCase();
    if (!userTrimmed) return;
    try {
      await unfollow(address, userTrimmed);
      setFollowedUsers(prev => prev.filter(u => String(u || '').trim().toLowerCase() !== userTrimmed));
      notifyUsersUpdated({
        removed: userTrimmed
      });
    } catch (error) {
      alert(`Error unfollowing user: ${error?.message || error}`);
    }
  };
  return {
    navigate,
    location,
    followedUsers,
    followedTopics,
    followedUsernames,
    listsLoading,
    listsError,
    isFollowTopicPending,
    isFollowUserPending,
    formatFollowTopicStatus,
    formatFollowUserStatus,
    handleUnfollowTopic,
    handleUnfollowUser
  };
}