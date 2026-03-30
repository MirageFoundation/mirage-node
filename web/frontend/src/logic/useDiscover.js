import { useState, useEffect, useRef, useCallback } from "react";
import Storage from "../utils/Storage";
import { getAllowedTagsParam } from "../utils/ContentTags";
import Api from "../utils/api";
import { subscribe, unsubscribe, fetchFollowedTopics, invalidateCache as invalidateTopicsCache } from "../utils/Subscriptions";
import { usePendingFollows } from "./useFollowState.js";
import { useLocation } from "react-router-dom";
export const tagColors = {
  porn: {
    bg: 'rgba(236, 72, 153, 0.18)',
    border: 'rgba(236, 72, 153, 0.50)',
    text: '#ec4899'
  },
  violence: {
    bg: 'rgba(185, 28, 28, 0.18)',
    border: 'rgba(185, 28, 28, 0.50)',
    text: '#b91c1c'
  },
  gore: {
    bg: 'rgba(185, 28, 28, 0.18)',
    border: 'rgba(185, 28, 28, 0.50)',
    text: '#b91c1c'
  },
  death: {
    bg: 'rgba(185, 28, 28, 0.18)',
    border: 'rgba(185, 28, 28, 0.50)',
    text: '#b91c1c'
  },
  sensitive: {
    bg: 'rgba(109, 40, 217, 0.18)',
    border: 'rgba(109, 40, 217, 0.50)',
    text: '#6d28d9'
  },
  default: {
    bg: '#e5e7eb',
    border: '#cbd5e1',
    text: '#0f172a'
  }
};
export function useDiscover({
  state
}) {
  const viewerAddress = Storage.load('publicKey', '') || 'guest';
  const [topics, setTopics] = useState([]);
  const [filteredTopics, setFilteredTopics] = useState([]);
  const [smallTopicsCount, setSmallTopicsCount] = useState(0);
  const [searchTerm, setSearchTerm] = useState('');
  const [searchResults, setSearchResults] = useState([]);
  const [isSearching, setIsSearching] = useState(false);
  const [loading, setLoading] = useState(true);
  const [followedTopicsSet, setFollowedTopicsSet] = useState(new Set());
  const [hoverTopic, setHoverTopic] = useState(null);
  const {
    isTopicPending,
    formatTopicStatus
  } = usePendingFollows();
  const mountedRef = useRef(true);
  const searchRequestId = useRef(0);
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);
  useEffect(() => {
    let alive = true;
    setLoading(true);
    Api.get('get_topics', {
      limit: 200,
      min_posts: 10,
      address: viewerAddress,
      allowed_tags: getAllowedTagsParam()
    }).then(data => {
      if (!alive || !mountedRef.current) return;
      if (data && Array.isArray(data.topics)) {
        const topicsList = data.topics.filter(t => t && t.topic && typeof t.topic === 'string' && t.topic.trim() !== '').map(t => ({
          topic: t.topic,
          post_count: t.post_count || t.count || 0,
          comment_count: t.comment_count || 0,
          dominant_tag: t.dominant_tag || null
        }));
        setTopics(topicsList);
        setFilteredTopics(topicsList);
        setSmallTopicsCount(data.small_topics_count || 0);
      } else {
        setTopics([]);
        setFilteredTopics([]);
        setSmallTopicsCount(0);
      }
      setLoading(false);
    }).catch(error => {
      if (!alive || !mountedRef.current) return;
      console.error('[DiscoverView] Failed to load topics:', error);
      setTopics([]);
      setFilteredTopics([]);
      setLoading(false);
    });
    return () => {
      alive = false;
    };
  }, [viewerAddress]);

  // Filter local topics and search API for more results
  useEffect(() => {
    const term = searchTerm.toLowerCase().trim().replace(/^#+/, '');
    if (!term) {
      setFilteredTopics(topics);
      setSearchResults([]);
      setIsSearching(false);
      return;
    }

    // Filter local topics immediately
    const filtered = topics.filter(t => {
      const topicName = String(t.topic || '').toLowerCase();
      return topicName.includes(term);
    });
    setFilteredTopics(filtered);

    // Also search API for topics with < 10 posts (debounced)
    if (term.length < 2) {
      setSearchResults([]);
      setIsSearching(false);
      return;
    }
    const requestId = searchRequestId.current + 1;
    searchRequestId.current = requestId;
    setIsSearching(true);
    const handle = setTimeout(async () => {
      try {
        const data = await Api.get('search_topics', {
          q: term,
          limit: 50,
          allowed_tags: getAllowedTagsParam()
        }, {
          timeoutMs: 8000
        });
        if (searchRequestId.current !== requestId || !mountedRef.current) return;
        const results = Array.isArray(data?.topics) ? data.topics : [];
        // Filter out topics already in the main list
        const existingLower = new Set(topics.map(t => t.topic.toLowerCase()));
        const newTopics = results.filter(t => t && t.topic && !existingLower.has(t.topic.toLowerCase())).map(t => ({
          topic: t.topic,
          post_count: t.post_count || t.count || 0,
          comment_count: t.comment_count || 0,
          dominant_tag: t.dominant_tag || null,
          fromSearch: true
        }));
        setSearchResults(newTopics);
      } catch (_) {
        if (searchRequestId.current === requestId) setSearchResults([]);
      } finally {
        if (searchRequestId.current === requestId) setIsSearching(false);
      }
    }, 250);
    return () => {
      searchRequestId.current += 1;
      clearTimeout(handle);
    };
  }, [searchTerm, topics]);
  useEffect(() => {
    let cancelled = false;
    const loadFollowedTopics = async () => {
      if (!viewerAddress || viewerAddress === 'guest') return;
      try {
        const list = await fetchFollowedTopics(viewerAddress);
        if (!cancelled && mountedRef.current) {
          setFollowedTopicsSet(new Set(list.map(t => t.toLowerCase())));
        }
      } catch (_) {}
    };
    loadFollowedTopics();
    return () => {
      cancelled = true;
    };
  }, [viewerAddress]);
  const isSubscribedTopic = useCallback(topic => {
    return followedTopicsSet.has(String(topic || '').toLowerCase());
  }, [followedTopicsSet]);
  const handleSubscribeToggle = useCallback(async topic => {
    const t = String(topic || '').toLowerCase();
    if (!t || isTopicPending(t)) return;
    const wasSubscribed = isSubscribedTopic(topic);
    try {
      if (wasSubscribed) {
        await unsubscribe(viewerAddress, topic);
        if (mountedRef.current) {
          setFollowedTopicsSet(prev => {
            const next = new Set(prev);
            next.delete(t);
            return next;
          });
        }
      } else {
        await subscribe(viewerAddress, topic);
        if (mountedRef.current) {
          setFollowedTopicsSet(prev => new Set([...prev, t]));
        }
      }
      invalidateTopicsCache();
    } catch (_) {}
  }, [viewerAddress, isTopicPending, isSubscribedTopic]);
  const location = useLocation();
  return {
    filteredTopics,
    smallTopicsCount,
    searchTerm,
    setSearchTerm,
    searchResults,
    isSearching,
    loading,
    hoverTopic,
    setHoverTopic,
    isTopicPending,
    formatTopicStatus,
    isSubscribedTopic,
    handleSubscribeToggle,
    location
  };
}