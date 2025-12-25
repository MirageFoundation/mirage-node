// Utilities for topic persistence and sorting
export function mergeAndSortTopics(storedTopicsInput, postsDict, preferredFirst = 'all') {
  const storedTopics = Array.isArray(storedTopicsInput) ? storedTopicsInput.filter(t => typeof t === 'string' && t.trim() !== '') : [];
  const posts = postsDict && typeof postsDict === 'object' ? Object.values(postsDict) : [];

  const counts = new Map();
  for (const p of posts) {
    if (!p || typeof p.topic !== 'string') continue;
    const t = p.topic.trim();
    if (!t) continue;
    counts.set(t, (counts.get(t) || 0) + 1);
  }

  const allTopicsSet = new Set(storedTopics);
  for (const t of counts.keys()) allTopicsSet.add(t);

  // Ensure preferredFirst exists and is first
  allTopicsSet.add(preferredFirst);

  const allTopics = Array.from(allTopicsSet);

  // Sort: preferredFirst first, then by count desc, then alpha
  allTopics.sort((a, b) => {
    if (a === preferredFirst && b !== preferredFirst) return -1;
    if (b === preferredFirst && a !== preferredFirst) return 1;
    const ca = counts.get(a) || 0;
    const cb = counts.get(b) || 0;
    if (cb !== ca) return cb - ca;
    return a.localeCompare(b);
  });

  return allTopics;
}


