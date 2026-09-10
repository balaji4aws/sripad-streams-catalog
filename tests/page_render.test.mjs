/**
 * Tests for the rendering half of search.html.
 *
 * Run with:  node --test "tests/**\/*.test.mjs"
 *
 * search.js holds the matching logic and is tested directly in
 * search_logic.test.mjs. This file covers the part that was previously not
 * checked by anything: the page's own script, which reads the DOM and writes
 * results into it.
 *
 * Rather than pull in a browser or a DOM library - which would be the project's
 * first heavyweight dependency, for one file - it runs the page's real inline
 * script against a small stub implementing only the handful of DOM methods that
 * script actually uses. The stub is deliberately dumb: if the page starts using
 * something it does not implement, the test fails loudly rather than passing on
 * a silent no-op.
 */

import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import test from 'node:test';

const repoRoot = join(dirname(fileURLToPath(import.meta.url)), '..');
const require = createRequire(import.meta.url);

// --- the stub DOM ----------------------------------------------------------

class StubElement {
  constructor(tagName) {
    this.tagName = tagName;
    this.children = [];
    this.attributes = {};
    this.listeners = {};
    this._text = '';
    this.className = '';
  }

  set textContent(value) {
    this._text = String(value);
    this.children = [];
  }

  get textContent() {
    return this._text + this.children.map((child) => child.textContent).join('');
  }

  appendChild(child) {
    this.children.push(child);
    return child;
  }

  replaceChildren() {
    this.children = [];
    this._text = '';
  }

  setAttribute(name, value) {
    this.attributes[name] = String(value);
  }

  getAttribute(name) {
    return Object.hasOwn(this.attributes, name) ? this.attributes[name] : null;
  }

  addEventListener(type, handler) {
    (this.listeners[type] ||= []).push(handler);
  }

  dispatch(type) {
    (this.listeners[type] || []).forEach((handler) => handler({ type }));
  }

  focus() {
    this.focused = true;
  }

  /** Every descendant with the given tag name, depth first. */
  findAll(tagName) {
    return this.children.flatMap((child) => [
      ...(child.tagName === tagName ? [child] : []),
      ...child.findAll(tagName)
    ]);
  }
}

class StubTextNode {
  constructor(text) {
    this.tagName = '#text';
    this._text = String(text);
    this.children = [];
  }

  get textContent() {
    return this._text;
  }

  findAll() {
    return [];
  }
}

/**
 * Load the page's inline script against a stub DOM.
 *
 * `fetchResult` is what the script's fetch() should resolve to; pass a
 * rejecting value to simulate a failed load.
 */
function loadPage({ fetchResult, initialQuery = '' } = {}) {
  const html = readFileSync(join(repoRoot, 'search.html'), 'utf8');
  const inline = html.split('<script>')[1].split('</script>')[0];

  const elements = {
    results: new StubElement('div'),
    status: new StubElement('div'),
    q: new StubElement('input'),
    topics: new StubElement('div')
  };
  elements.q.value = initialQuery;

  const document = {
    getElementById: (id) => {
      const element = elements[id];
      if (!element) throw new Error(`stub DOM has no element with id "${id}"`);
      return element;
    },
    createElement: (tagName) => new StubElement(tagName),
    createTextNode: (text) => new StubTextNode(text)
  };

  const settled = fetchResult;
  const fetch = () => Promise.resolve({
    ok: settled.ok !== false,
    status: settled.status ?? 200,
    statusText: settled.statusText ?? 'OK',
    json: () => Promise.resolve(settled.body)
  });

  const window = { CatalogSearch: require(join(repoRoot, 'search.js')) };

  // eslint-disable-next-line no-new-func -- running the shipped script is the point
  new Function('document', 'window', 'fetch', inline)(document, window, fetch);

  return {
    elements,
    /** Let the script's promise chain settle. */
    settle: () => new Promise((resolve) => setImmediate(resolve))
  };
}

const catalog = {
  groups: [
    {
      label: 'Satyatma Sandhya (Kannada)', category: 'Satyatma Sandhya', language: 'kannada', count: 2,
      search_words: ['kannada', 'sandhya', 'satyatma'],
      videos: [
        { seq: 1, total: 2, date: '2023-06-01', title: 'Satyatma Sandhya Kannada Day1',
          video_id: 'a1', url: 'https://www.youtube.com/watch?v=a1', duration_min: 61.5, view_count: 10 },
        { seq: 2, total: 2, date: '2023-06-24', title: 'Satyatma Sandhya Kannada Final Day',
          video_id: 'a2', url: 'https://www.youtube.com/watch?v=a2', duration_min: 45, view_count: 20 }
      ]
    },
    {
      label: 'Satyatma Sandhya (English)', category: 'Satyatma Sandhya', language: 'english', count: 1,
      search_words: ['english', 'sandhya', 'satyatma'],
      videos: [
        { seq: 1, total: 1, date: '2023-05-02', title: 'Satyatma Sandhya English Day1',
          video_id: 'b1', url: 'https://www.youtube.com/watch?v=b1', duration_min: 30, view_count: 5 }
      ]
    },
    {
      label: 'Manimanjari (Kannada)', category: 'Manimanjari (Kannada)', language: 'kannada', count: 3,
      search_words: ['kannada', 'manimanjari'],
      videos: [1, 2, 3].map((n) => ({
        seq: n, total: 3, date: `2026-05-0${n}`, title: `Manimanjari Kannada Day${n}`,
        video_id: `c${n}`, url: `https://www.youtube.com/watch?v=c${n}`, duration_min: 50, view_count: 1
      }))
    }
  ]
};

// --- tests -----------------------------------------------------------------

test('a successful load reports the sequence count and builds the topic buttons', async () => {
  const page = loadPage({ fetchResult: { body: catalog } });
  await page.settle();

  assert.match(page.elements.status.textContent, /Loaded 3 sequences/);

  const buttons = page.elements.topics.children;
  assert.equal(buttons.length, 2, 'two categories, with the Kannada/English tracks summed into one');
  // Largest category first: Manimanjari has 3 videos, Satyatma Sandhya has 3
  // too, so the tie breaks on name.
  assert.deepEqual(buttons.map((b) => b.textContent),
    ['Manimanjari (Kannada) (3)', 'Satyatma Sandhya (3)']);
});

test('topic buttons are real buttons, labelled, and keyboard-operable', async () => {
  const page = loadPage({ fetchResult: { body: catalog } });
  await page.settle();

  for (const button of page.elements.topics.children) {
    assert.equal(button.tagName, 'button', 'must be a <button>, not a clickable <div>');
    assert.equal(button.type, 'button');
    assert.match(button.getAttribute('aria-label'), /^Search for .+, \d+ videos$/);
    assert.ok(button.listeners.click, 'must respond to activation');
  }
});

test('activating a topic button runs that search', async () => {
  const page = loadPage({ fetchResult: { body: catalog } });
  await page.settle();

  const manimanjari = page.elements.topics.children[0];
  manimanjari.dispatch('click');

  assert.equal(page.elements.q.value, 'Manimanjari (Kannada)');
  assert.ok(page.elements.q.focused, 'focus should move to the search box for further editing');
  assert.match(page.elements.status.textContent, /1 sequence\(s\) found, 3 video\(s\) total/);
  assert.equal(page.elements.results.children.length, 1);
});

test('typing renders one section per matching sequence, in watch order', async () => {
  const page = loadPage({ fetchResult: { body: catalog } });
  await page.settle();

  page.elements.q.value = 'satyatma kannada';
  page.elements.q.dispatch('input');

  const sections = page.elements.results.children;
  assert.equal(sections.length, 1);
  assert.match(sections[0].findAll('h2')[0].textContent,
    /Satyatma Sandhya \(Kannada\) \(2 videos, watch in order below\)/);

  const links = sections[0].findAll('a');
  assert.deepEqual(links.map((a) => a.textContent),
    ['Satyatma Sandhya Kannada Day1', 'Satyatma Sandhya Kannada Final Day']);
  // Oldest first, so the sequence reads as watch order.
  assert.deepEqual(links.map((a) => a.href),
    ['https://www.youtube.com/watch?v=a1', 'https://www.youtube.com/watch?v=a2']);
});

test('result links open safely in a new tab', async () => {
  const page = loadPage({ fetchResult: { body: catalog } });
  await page.settle();
  page.elements.q.value = 'manimanjari';
  page.elements.q.dispatch('input');

  for (const link of page.elements.results.children[0].findAll('a')) {
    assert.equal(link.target, '_blank');
    assert.equal(link.rel, 'noopener noreferrer');
  }
});

test('each result table is described and its headers are marked as headers', async () => {
  const page = loadPage({ fetchResult: { body: catalog } });
  await page.settle();
  page.elements.q.value = 'manimanjari';
  page.elements.q.dispatch('input');

  const section = page.elements.results.children[0];
  const caption = section.findAll('caption')[0];
  assert.match(caption.textContent, /Manimanjari \(Kannada\), in watch order/);
  assert.equal(caption.className, 'visually-hidden', 'the caption is for screen readers only');

  const headers = section.findAll('th');
  assert.deepEqual(headers.map((th) => th.textContent), ['#', 'Title', 'Date', 'Min']);
  assert.ok(headers.every((th) => th.scope === 'col'));
});

test('titles are written as text, never as markup', async () => {
  const hostile = structuredClone(catalog);
  hostile.groups[2].videos[0].title = '<img src=x onerror="alert(1)">';
  const page = loadPage({ fetchResult: { body: hostile } });
  await page.settle();
  page.elements.q.value = 'manimanjari';
  page.elements.q.dispatch('input');

  const link = page.elements.results.children[0].findAll('a')[0];
  // textContent, not innerHTML: the string is shown, not interpreted.
  assert.equal(link.textContent, '<img src=x onerror="alert(1)">');
});

test('a search with no matches says so and clears the results', async () => {
  const page = loadPage({ fetchResult: { body: catalog } });
  await page.settle();

  page.elements.q.value = 'manimanjari';
  page.elements.q.dispatch('input');
  assert.equal(page.elements.results.children.length, 1);

  page.elements.q.value = 'zzzqqq';
  page.elements.q.dispatch('input');
  assert.match(page.elements.status.textContent, /No matching sequences found for "zzzqqq"/);
  assert.equal(page.elements.results.children.length, 0);
});

test('clearing the search restores the full topic list', async () => {
  const page = loadPage({ fetchResult: { body: catalog } });
  await page.settle();

  page.elements.q.value = 'english';
  page.elements.q.dispatch('input');
  assert.equal(page.elements.topics.children.length, 1, 'topics filter down with the results');

  page.elements.q.value = '';
  page.elements.q.dispatch('input');
  assert.equal(page.elements.topics.children.length, 2);
  assert.match(page.elements.status.textContent, /Type a search term above/);
});

test('a query typed before the catalog arrives is rendered once it does', async () => {
  // The input listener used to be registered inside the fetch callback, so
  // anything typed during loading was silently ignored.
  const page = loadPage({ fetchResult: { body: catalog }, initialQuery: 'manimanjari' });
  await page.settle();

  assert.equal(page.elements.results.children.length, 1);
  assert.match(page.elements.status.textContent, /1 sequence\(s\) found/);
});

test('a failed load explains how to fix it instead of failing silently', async () => {
  const page = loadPage({ fetchResult: { ok: false, status: 404, statusText: 'Not Found' } });
  await page.settle();

  const status = page.elements.status.textContent;
  assert.match(status, /Could not load output\/sequences\.json/);
  assert.match(status, /404/);
  assert.match(status, /http\.server/, 'should tell the reader to serve the folder over HTTP');
});

test('an empty catalog is reported rather than looking like a broken page', async () => {
  const page = loadPage({ fetchResult: { body: { groups: [] } } });
  await page.settle();
  assert.match(page.elements.status.textContent, /contains no sequences/);
});
