import { useEffect, useState } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import Storage from "../utils/Storage";
import Api from "../utils/api";
import * as tx from "../utils/tx";
import { usePendingBlocks } from "./usePendingBlocks.js";
import { resolveUsernames as resolveUsernamesCached } from "../utils/UsernameCache";
export const shortenAddress = addr => {
  if (!addr) return '';
  if (addr.length <= 24) return addr;
  return `${addr.slice(0, 14)}...${addr.slice(-8)}`;
};
export function useBlocks({
  state
}) {
  const navigate = useNavigate();
  const location = useLocation();
  const address = state && state.publicKey ? state.publicKey : Storage.load('publicKey', '');
  const [blockedUsers, setBlockedUsers] = useState([]);
  const [blockedPosts, setBlockedPosts] = useState([]);
  const [blockedTopics, setBlockedTopics] = useState([]);
  const [blockedUsernames, setBlockedUsernames] = useState({});
  const [listsLoading, setListsLoading] = useState(false);
  const [listsError, setListsError] = useState('');
  const {
    isTopicPending,
    isUserPending,
    isPostPending,
    formatTopicStatus,
    formatUserStatus,
    formatPostStatus
  } = usePendingBlocks();
  useEffect(() => {
    if (!address) return;
    let cancelled = false;
    const fetchBlocks = async () => {
      setListsLoading(true);
      setListsError('');
      try {
        const data = await Api.get('get_user_blocked', {
          address
        });
        if (cancelled) return;
        setBlockedUsers(data?.blocked_users || []);
        setBlockedPosts(data?.blocked_posts || []);
        setBlockedTopics(data?.blocked_topics || []);
      } catch (err) {
        if (!cancelled) {
          setListsError(err?.message || 'Failed to load blocked items');
        }
      } finally {
        if (!cancelled) {
          setListsLoading(false);
        }
      }
    };
    fetchBlocks();
    return () => {
      cancelled = true;
    };
  }, [address]);
  useEffect(() => {
    const addrs = blockedUsers.map(a => String(a || '').trim()).filter(Boolean);
    if (addrs.length === 0) {
      setBlockedUsernames({});
      return;
    }
    let cancelled = false;
    const resolveAll = async () => {
      try {
        const mapping = await resolveUsernamesCached(addrs, {
          timeoutMs: 5000
        });
        if (cancelled) return;
        const result = {};
        for (const addr of addrs) {
          const lower = String(addr || '').toLowerCase();
          const uname = mapping[lower];
          result[addr] = uname || addr;
        }
        setBlockedUsernames(result);
      } catch {
        if (cancelled) return;
        const result = {};
        addrs.forEach(a => {
          result[a] = a;
        });
        setBlockedUsernames(result);
      }
    };
    resolveAll();
    return () => {
      cancelled = true;
    };
  }, [blockedUsers]);
  const handleUnblockTopic = async (e, topic) => {
    if (e && typeof e.stopPropagation === 'function') e.stopPropagation();
    const topicTrimmed = String(topic || '').trim().toLowerCase();
    if (!topicTrimmed) return;
    try {
      const result = await tx.unblockTopic(topicTrimmed);
      if (result && result.success) {
        setBlockedTopics(prev => prev.filter(t => String(t || '').trim().toLowerCase() !== topicTrimmed));
      } else {
        alert(`Failed to unblock topic: ${result?.error || 'Unknown error'}`);
      }
    } catch (error) {
      alert(`Error unblocking topic: ${error?.message || error}`);
    }
  };
  const handleUnblockUser = async (e, userAddr) => {
    if (e && typeof e.stopPropagation === 'function') e.stopPropagation();
    const userTrimmed = String(userAddr || '').trim().toLowerCase();
    if (!userTrimmed) return;
    try {
      const result = await tx.unblockUser(userTrimmed);
      if (result && result.success) {
        setBlockedUsers(prev => prev.filter(u => String(u || '').trim().toLowerCase() !== userTrimmed));
      } else {
        alert(`Failed to unblock user: ${result?.error || 'Unknown error'}`);
      }
    } catch (error) {
      alert(`Error unblocking user: ${error?.message || error}`);
    }
  };
  const handleUnblockPost = async (e, postId) => {
    if (e && typeof e.stopPropagation === 'function') e.stopPropagation();
    const postTrimmed = String(postId || '').trim().toLowerCase();
    if (!postTrimmed) return;
    try {
      const result = await tx.unblockPost(postTrimmed);
      if (result && result.success) {
        setBlockedPosts(prev => prev.filter(p => String(p || '').trim().toLowerCase() !== postTrimmed));
      } else {
        alert(`Failed to unblock post: ${result?.error || 'Unknown error'}`);
      }
    } catch (error) {
      alert(`Error unblocking post: ${error?.message || error}`);
    }
  };
  return {
    navigate,
    location,
    blockedUsers,
    blockedPosts,
    blockedTopics,
    blockedUsernames,
    listsLoading,
    listsError,
    isTopicPending,
    isUserPending,
    isPostPending,
    formatTopicStatus,
    formatUserStatus,
    formatPostStatus,
    handleUnblockTopic,
    handleUnblockUser,
    handleUnblockPost
  };
}