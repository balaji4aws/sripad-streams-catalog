/**
 * Tests for search.js, the matching logic behind the search page.
 *
 * Run with:  node --test tests/*.test.mjs
 *
 * These use Node's built-in test runner and assert module, so like the Python
 * tests they need nothing installed. They exercise the real search.js the page
 * loads, and the second half runs it against the committed sequences.json so a
 * change to the catalog that breaks a real search is caught here.
 */

import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { readFileSync, existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import test from 'node:test';

const repoRoot = join(dirname(fileURLToPath(import.meta.url)), '..');
const require = createRequire(import.meta.url);
const { tokenize, isNumeric, wordHit, searchGroups, topicTotals } =
  require(join(repoRoot, 'search.js'));

/** A minimal sequence, so each test only states what it cares about. */
function sequence(label, category, words, count = 1) {
  return { label, category, count, search_words: words.slice().sort() };
}

test('tokenize splits on punctuation and lowercases', () => {
  assert.deepEqual(tokenize('Sandhyavandana-ONLINE kannada, Day2!'),
    ['sandhyavandana', 'online', 'kannada', 'day2']);
  assert.deepEqual(tokenize(''), []);
  assert.deepEqual(tokenize('   '), []);
});

test('isNumeric accepts only digits', () => {
  assert.equal(isNumeric('28'), true);
  assert.equal(isNumeric('28a'), false);
  assert.equal(isNumeric(''), false);
});

test('a longer query word matches a shorter word in the sequence', () => {
  // A search for the full "sandhyavandana" must find titles that only say
  // "sandhya".
  assert.equal(wordHit('sandhyavandana', ['sandhya', 'kannada']), true);
});

test('a shorter query word matches a longer word in the sequence', () => {
  // "kannada" must match a title that ran it onto an adjacent word.
  assert.equal(wordHit('kannada', ['sandhyavandanakannada']), true);
});

test('numbers must match exactly, never as part of a longer number', () => {
  assert.equal(wordHit('28', ['28', 'moorthi']), true);
  // The bug this guards: "2026" is a year in nearly every title, so a bare
  // "2" must not match it.
  assert.equal(wordHit('2', ['2026', 'sandhya']), false);
  assert.equal(wordHit('2', ['2', 'sandhya']), true);
});

test('very short words match exactly rather than being dropped', () => {
  // Returning false for every short word made any query containing one return
  // nothing at all, because matching is an AND across words.
  assert.equal(wordHit('om', ['om', 'stotra']), true);
  assert.equal(wordHit('om', ['omkara', 'stotra']), false);
});

test('one and two letter words in the sequence are not used as substrings', () => {
  // A two-letter fragment is inside a huge share of words, so it must not
  // make a whole sequence match.
  assert.equal(wordHit('sandhyavandana', ['sa', 'nd']), false);
  // Three letters and up are used, which is deliberate: matching is loose in
  // both directions so that partial and run-together spellings still work.
  assert.equal(wordHit('sandhyavandana', ['sandhya']), true);
});

test('searchGroups requires every query word to match', () => {
  const groups = [
    sequence('Satyatma Sandhya (Kannada)', 'Satyatma Sandhya', ['satyatma', 'sandhya', 'kannada']),
    sequence('Satyatma Sandhya (English)', 'Satyatma Sandhya', ['satyatma', 'sandhya', 'english']),
    sequence('Manimanjari (Kannada)', 'Manimanjari', ['manimanjari', 'kannada'])
  ];
  assert.deepEqual(searchGroups(groups, 'sandhya kannada').map((g) => g.label),
    ['Satyatma Sandhya (Kannada)']);
  assert.equal(searchGroups(groups, 'kannada').length, 2);
  assert.equal(searchGroups(groups, 'sandhya kannada english').length, 0);
});

test('an empty query matches nothing rather than everything', () => {
  const groups = [sequence('A', 'A', ['alpha'])];
  assert.deepEqual(searchGroups(groups, ''), []);
  assert.deepEqual(searchGroups(groups, '   '), []);
  assert.deepEqual(searchGroups(groups, '!!!'), []);
});

test('topicTotals sums a category across its languages, largest first', () => {
  const groups = [
    sequence('Satyatma Sandhya (Kannada)', 'Satyatma Sandhya', ['a'], 13),
    sequence('Satyatma Sandhya (English)', 'Satyatma Sandhya', ['a'], 11),
    sequence('Manimanjari (Kannada)', 'Manimanjari', ['b'], 38)
  ];
  assert.deepEqual(topicTotals(groups), [
    { category: 'Manimanjari', count: 38 },
    { category: 'Satyatma Sandhya', count: 24 }
  ]);
});

test('topicTotals breaks ties on the category name, so order is stable', () => {
  const groups = [sequence('Z', 'Zebra', ['z'], 2), sequence('A', 'Alpha', ['a'], 2)];
  assert.deepEqual(topicTotals(groups).map((t) => t.category), ['Alpha', 'Zebra']);
});

// --- against the committed catalog ------------------------------------------

const sequencesPath = join(repoRoot, 'output', 'sequences.json');

test('real searches over the committed catalog', { skip: !existsSync(sequencesPath) }, async (t) => {
  const { groups } = JSON.parse(readFileSync(sequencesPath, 'utf8'));

  await t.test('the catalog is not empty', () => {
    assert.ok(groups.length > 0);
  });

  await t.test('a language search returns only that language', () => {
    const results = searchGroups(groups, 'sandhyavandana kannada');
    assert.ok(results.length > 0, 'expected at least one Kannada sandhyavandana sequence');
    for (const group of results) {
      assert.ok(!group.label.includes('(English)'), `unexpected English track: ${group.label}`);
      assert.ok(!group.label.includes('(Marathi)'), `unexpected Marathi track: ${group.label}`);
    }
  });

  await t.test('English and Kannada tracks of one series are separate results', () => {
    const english = searchGroups(groups, 'satyatma english');
    const kannada = searchGroups(groups, 'satyatma kannada');
    assert.ok(english.length > 0 && kannada.length > 0);
    const overlap = english.filter((g) => kannada.some((k) => k.label === g.label));
    assert.deepEqual(overlap, []);
  });

  await t.test('a bare "2" matches only sequences with a literal "2"', () => {
    const expected = groups.filter((g) => g.search_words.includes('2')).length;
    assert.equal(searchGroups(groups, '2').length, expected);
  });

  await t.test('nonsense returns nothing', () => {
    assert.deepEqual(searchGroups(groups, 'zzzqqq'), []);
  });

  await t.test('every topic total is covered by the sequences it sums', () => {
    const totals = topicTotals(groups);
    const summed = totals.reduce((sum, topic) => sum + topic.count, 0);
    const allVideos = groups.reduce((sum, group) => sum + group.count, 0);
    assert.equal(summed, allVideos);
  });
});
