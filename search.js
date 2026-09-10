/**
 * search.js - the pure search logic behind search.html.
 *
 * This is kept separate from the page so it can be tested directly, without a
 * browser or a DOM. It holds no state and touches nothing outside its
 * arguments: search.html owns all the rendering, this file owns all the
 * matching. There is still no build step and no framework - the page loads
 * this as a plain script.
 *
 * In a browser it defines the global `CatalogSearch`. Under Node it exports
 * the same object, which is how tests/search_logic.test.mjs reaches it.
 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) {
    module.exports = factory();
  } else {
    root.CatalogSearch = factory();
  }
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  // Below this length a query word is matched exactly rather than as a
  // substring, because a one or two character fragment matches almost
  // everything and narrows nothing down.
  const MIN_SUBSTRING_LENGTH = 3;

  /** Split text into lowercase alphanumeric words. */
  function tokenize(text) {
    return String(text).toLowerCase().match(/[a-z0-9]+/g) || [];
  }

  function isNumeric(text) {
    return /^[0-9]+$/.test(text);
  }

  /**
   * Does `queryWord` meaningfully appear in a sequence's word list?
   *
   * Longer words use a bidirectional substring match, so "sandhyavandana"
   * finds a sequence whose titles only ever say "sandhya", and "kannada"
   * matches a title that ran it onto an adjacent word with no space
   * ("Sandhyavandanakannada").
   *
   * Two kinds of word fall back to an exact match instead:
   *  - Numbers, e.g. "28" from "28 Moorthi Stuti". Substring matching would
   *    let a bare "2" match "2026", a year in nearly every title.
   *  - Words shorter than MIN_SUBSTRING_LENGTH, which are too short to narrow
   *    anything down as a substring. Matching them exactly means a genuinely
   *    short search term still finds its sequence instead of returning nothing.
   */
  function wordHit(queryWord, sequenceWords) {
    if (isNumeric(queryWord) || queryWord.length < MIN_SUBSTRING_LENGTH) {
      return sequenceWords.indexOf(queryWord) !== -1;
    }
    return sequenceWords.some(function (word) {
      if (word.length < MIN_SUBSTRING_LENGTH) return false;
      return word.indexOf(queryWord) !== -1 || queryWord.indexOf(word) !== -1;
    });
  }

  /**
   * Sequences matching every word in `query`.
   *
   * The AND is the point: "sandhyavandana kannada" returns Kannada
   * sandhyavandana sequences, not every Kannada video plus every
   * sandhyavandana video. An empty query matches nothing rather than
   * everything, so the page shows its prompt instead of the whole catalog.
   */
  function searchGroups(groups, query) {
    const queryWords = tokenize(query);
    if (queryWords.length === 0) return [];
    return groups.filter(function (group) {
      return queryWords.every(function (word) { return wordHit(word, group.search_words); });
    });
  }

  /**
   * Per-category video totals, largest first.
   *
   * A category's languages are summed into one entry, so "Satyatma Sandhya"
   * counts its English, Kannada and Marathi sequences together. Ties break on
   * the category name so the order does not shift between renders.
   *
   * Returns an array of `{ category, count }`.
   */
  function topicTotals(groups) {
    const totals = new Map();
    groups.forEach(function (group) {
      totals.set(group.category, (totals.get(group.category) || 0) + group.count);
    });
    return Array.from(totals, function (entry) {
      return { category: entry[0], count: entry[1] };
    }).sort(function (a, b) {
      return b.count - a.count || a.category.localeCompare(b.category);
    });
  }

  return {
    MIN_SUBSTRING_LENGTH: MIN_SUBSTRING_LENGTH,
    tokenize: tokenize,
    isNumeric: isNumeric,
    wordHit: wordHit,
    searchGroups: searchGroups,
    topicTotals: topicTotals
  };
});
