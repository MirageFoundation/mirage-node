import { mergeAndSortTopics } from '../Topics';

describe('mergeAndSortTopics', () => {
  test('includes stored topics when posts are empty and keeps "all" first', () => {
    const stored = ['all', 'news', 'tech'];
    const posts = {};
    const out = mergeAndSortTopics(stored, posts, 'all');
    expect(out[0]).toBe('all');
    expect(out).toEqual(['all', 'news', 'tech']);
  });

  test('merges topics from posts and stored without duplicates', () => {
    const stored = ['all', 'news', 'retro'];
    const posts = {
      a: { topic: 'tech', title: 't1' },
      b: { topic: 'news', title: 't2' },
    };
    const out = mergeAndSortTopics(stored, posts, 'all');
    expect(out[0]).toBe('all');
    expect(new Set(out)).toEqual(new Set(['all', 'news', 'retro', 'tech']));
  });

  test('sorts by count desc then alpha (after "all")', () => {
    const stored = ['all', 'zoo', 'alpha'];
    const posts = {
      a: { topic: 'beta', title: '1' },
      b: { topic: 'beta', title: '2' },
      c: { topic: 'gamma', title: '3' },
      d: { topic: 'alpha', title: '4' },
    };
    const out = mergeAndSortTopics(stored, posts, 'all');
    // "all" always first, then beta (count 2), then alpha (count 1), then gamma (count 1, alpha < gamma so alpha first), then zoo (count 0)
    expect(out.slice(0, 1)).toEqual(['all']);
    expect(out[1]).toBe('beta');
    expect(out[2]).toBe('alpha');
    expect(out[3]).toBe('gamma');
    expect(out.includes('zoo')).toBe(true);
  });

  test('ignores invalid or empty topics', () => {
    const stored = ['all', '', null, 'valid'];
    const posts = {
      a: { topic: ' ', title: '1' },
      b: { topic: '', title: '2' },
      c: { topic: 'ok', title: '3' },
    };
    const out = mergeAndSortTopics(stored, posts, 'all');
    expect(out[0]).toBe('all');
    expect(new Set(out)).toEqual(new Set(['all', 'valid', 'ok']));
  });
});


