/**
 * browser_check.mjs - drive search.html in a real browser and check it.
 *
 * Run with:  make test-browser      (or: node tests/browser_check.mjs)
 *
 * The other test files check the page's logic and the structure it builds
 * against a stub DOM. This one loads the page into an actual browser, with a
 * real CSS engine and real layout, and then:
 *
 *   1. exercises the page the way a person would - typing in the search box,
 *      activating topic buttons, tabbing to them from the keyboard;
 *   2. reads back COMPUTED colours and font metrics for every element that
 *      renders text, and checks each one against the WCAG AA contrast
 *      threshold. Computed values are what a reader actually sees, so this
 *      catches a colour that only fails once inheritance and cascade are
 *      resolved - something no amount of reading the stylesheet can prove.
 *
 * It talks to Chrome over the DevTools Protocol using Node's built-in
 * WebSocket, and serves the folder from a small built-in HTTP server, so it
 * adds no dependencies. It is deliberately NOT part of `make check`: it needs
 * a browser installed, which CI's Python and Node jobs do not.
 */

import { spawn } from 'node:child_process';
import { createServer } from 'node:http';
import { mkdtemp, readFile, rm } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, extname, join, normalize } from 'node:path';
import { fileURLToPath } from 'node:url';

const repoRoot = join(dirname(fileURLToPath(import.meta.url)), '..');

const CHROME_CANDIDATES = [
  '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
  '/Applications/Chromium.app/Contents/MacOS/Chromium',
  '/usr/bin/google-chrome',
  '/usr/bin/chromium',
  '/usr/bin/chromium-browser'
];

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.md': 'text/markdown; charset=utf-8'
};

// --- reporting -------------------------------------------------------------

let failures = 0;
let checks = 0;

function check(ok, label, detail = '') {
  checks += 1;
  if (!ok) failures += 1;
  console.log(`  ${ok ? 'PASS' : 'FAIL'}  ${label}${detail ? `\n          ${detail}` : ''}`);
}

function section(title) {
  console.log(`\n${title}`);
}

// --- static file server ----------------------------------------------------

function startServer() {
  const server = createServer(async (request, response) => {
    const path = normalize(decodeURIComponent(request.url.split('?')[0])).replace(/^(\.\.[/\\])+/, '');
    const file = join(repoRoot, path);
    if (!file.startsWith(repoRoot) || !existsSync(file)) {
      response.writeHead(404).end('not found');
      return;
    }
    response.writeHead(200, { 'Content-Type': MIME[extname(file)] ?? 'application/octet-stream' });
    response.end(await readFile(file));
  });
  return new Promise((resolve) => {
    server.listen(0, '127.0.0.1', () => resolve({ server, port: server.address().port }));
  });
}

// --- Chrome over the DevTools Protocol -------------------------------------

const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function launchChrome() {
  const binary = CHROME_CANDIDATES.find((candidate) => existsSync(candidate));
  if (!binary) {
    console.log('No Chrome or Chromium found. Looked in:');
    CHROME_CANDIDATES.forEach((candidate) => console.log(`  ${candidate}`));
    process.exit(2);
  }

  const profile = await mkdtemp(join(tmpdir(), 'catalog-browser-check-'));
  const chrome = spawn(binary, [
    '--headless=new',
    '--remote-debugging-port=0',
    `--user-data-dir=${profile}`,
    '--no-first-run',
    '--no-default-browser-check',
    '--disable-extensions',
    '--disable-gpu',
    '--hide-scrollbars',
    '--window-size=1200,900',
    'about:blank'
  ], { stdio: ['ignore', 'ignore', 'pipe'] });

  // Chrome writes the port it actually chose into the profile directory.
  const portFile = join(profile, 'DevToolsActivePort');
  for (let attempt = 0; attempt < 100; attempt += 1) {
    if (existsSync(portFile)) {
      const [port] = (await readFile(portFile, 'utf8')).split('\n');
      if (port) {
        const response = await fetch(`http://127.0.0.1:${port}/json/version`);
        const { webSocketDebuggerUrl } = await response.json();
        return { chrome, profile, webSocketDebuggerUrl, binary };
      }
    }
    await delay(100);
  }
  chrome.kill();
  throw new Error('Chrome did not report a debugging port within 10s');
}

/** Minimal DevTools Protocol client: send a command, await its reply. */
function connect(url) {
  const socket = new WebSocket(url);
  const pending = new Map();
  const events = new Map();
  let nextId = 0;

  socket.addEventListener('message', (message) => {
    const frame = JSON.parse(message.data);
    if (frame.id !== undefined && pending.has(frame.id)) {
      const { resolve, reject } = pending.get(frame.id);
      pending.delete(frame.id);
      frame.error ? reject(new Error(JSON.stringify(frame.error))) : resolve(frame.result);
    } else if (frame.method && events.has(frame.method)) {
      events.get(frame.method).forEach((handler) => handler(frame.params));
    }
  });

  const ready = new Promise((resolve, reject) => {
    socket.addEventListener('open', resolve, { once: true });
    socket.addEventListener('error', reject, { once: true });
  });

  return {
    ready,
    send(method, params = {}, sessionId) {
      const id = (nextId += 1);
      return new Promise((resolve, reject) => {
        pending.set(id, { resolve, reject });
        socket.send(JSON.stringify({ id, method, params, sessionId }));
      });
    },
    on(method, handler) {
      if (!events.has(method)) events.set(method, []);
      events.get(method).push(handler);
    },
    close: () => socket.close()
  };
}

// --- main ------------------------------------------------------------------

// With no argument the page is served from this folder, which is what CI does.
// Pass a URL to run the same checks against a deployed copy:
//   node tests/browser_check.mjs https://example.github.io/repo/search.html
const targetUrl = process.argv[2];

const { server, port } = await startServer();
const pageUrl = targetUrl ?? `http://127.0.0.1:${port}/search.html`;
const { chrome, profile, webSocketDebuggerUrl, binary } = await launchChrome();
const client = connect(webSocketDebuggerUrl);
await client.ready;

const consoleErrors = [];
const failedRequests = [];
let sessionId;

async function cleanup() {
  client.close();
  chrome.kill();
  server.close();
  await rm(profile, { recursive: true, force: true }).catch(() => {});
}

try {
  const { targetId } = await client.send('Target.createTarget', { url: 'about:blank' });
  ({ sessionId } = await client.send('Target.attachToTarget', { targetId, flatten: true }));

  const send = (method, params) => client.send(method, params, sessionId);
  const evaluate = async (expression) => {
    const { result, exceptionDetails } = await send('Runtime.evaluate', {
      expression, returnByValue: true, awaitPromise: true
    });
    if (exceptionDetails) throw new Error(exceptionDetails.exception?.description ?? 'evaluate threw');
    return result.value;
  };

  await send('Page.enable');
  await send('Runtime.enable');
  await send('Log.enable');
  await send('Network.enable');

  client.on('Runtime.consoleAPICalled', ({ type, args }) => {
    if (type === 'error') consoleErrors.push(args.map((a) => a.value ?? a.description).join(' '));
  });
  client.on('Log.entryAdded', ({ entry }) => {
    if (entry.level === 'error') consoleErrors.push(entry.text);
  });
  client.on('Network.loadingFailed', ({ errorText }) => failedRequests.push(errorText));
  client.on('Network.responseReceived', ({ response }) => {
    if (response.status >= 400) failedRequests.push(`HTTP ${response.status} ${response.url}`);
  });

  console.log(`Browser : ${binary.split('/').pop()}`);
  console.log(`Page    : ${pageUrl}`);

  const loaded = new Promise((resolve) => client.on('Page.loadEventFired', resolve));
  await send('Page.navigate', { url: pageUrl });
  await loaded;
  // Give the page's fetch of sequences.json time to resolve and render.
  await evaluate(`new Promise((resolve) => {
    const ready = () => document.querySelectorAll('#topics button').length > 0;
    if (ready()) return resolve(true);
    const timer = setInterval(() => { if (ready()) { clearInterval(timer); resolve(true); } }, 50);
    setTimeout(() => { clearInterval(timer); resolve(false); }, 5000);
  })`);

  // --- 1. loading ---------------------------------------------------------

  section('1. Page load');
  check(failedRequests.length === 0, 'every request succeeded', failedRequests.join('; '));
  check(consoleErrors.length === 0, 'no console errors', consoleErrors.join('; '));

  const loadState = await evaluate(`({
    status: document.getElementById('status').textContent,
    topics: document.querySelectorAll('#topics button').length,
    title: document.title,
    scriptLoaded: typeof window.CatalogSearch
  })`);
  check(/Loaded \d+ sequences/.test(loadState.status),
    'status reports the loaded catalog', loadState.status);
  check(loadState.scriptLoaded === 'object', 'search.js loaded into the page',
    `typeof window.CatalogSearch = ${loadState.scriptLoaded}`);
  check(loadState.topics === 40, `all 40 topic buttons rendered (got ${loadState.topics})`);

  const freshness = await evaluate(`document.getElementById('freshness').textContent`);
  check(/recordings/.test(freshness) && /last scanned \d+ \w+ \d{4}/.test(freshness),
    'page states how current the catalogue is', freshness);

  // --- 2. searching -------------------------------------------------------

  section('2. Typing a search');
  const typed = await evaluate(`(() => {
    const q = document.getElementById('q');
    q.value = 'sandhyavandana kannada';
    q.dispatchEvent(new Event('input', { bubbles: true }));
    return {
      status: document.getElementById('status').textContent,
      labels: [...document.querySelectorAll('#results h2')].map((h) => h.textContent.trim()),
      rows: document.querySelectorAll('#results tbody tr').length,
      topics: document.querySelectorAll('#topics button').length
    };
  })()`);
  check(typed.labels.length === 3, `three sequences rendered (got ${typed.labels.length})`,
    typed.labels.join(' | '));
  check(typed.labels.every((label) => /Kannada/i.test(label)),
    'every result is a Kannada track', typed.labels.join(' | '));
  check(/sequence\(s\) found/.test(typed.status), 'status updated', typed.status);
  check(typed.topics === 3, `topic buttons filtered down to the matches (got ${typed.topics})`);

  section('3. Result rows');
  const rows = await evaluate(`(() => {
    const first = document.querySelector('#results .group');
    return {
      seq: [...first.querySelectorAll('td.seq')].map((td) => td.textContent),
      links: [...first.querySelectorAll('a.watch')].map((a) => ({
        href: a.href, rel: a.rel, target: a.target, text: a.textContent
      })),
      caption: first.querySelector('caption')?.textContent ?? null,
      captionHidden: (() => {
        const c = first.querySelector('caption');
        if (!c) return null;
        const r = c.getBoundingClientRect();
        return r.width <= 1 && r.height <= 1;
      })(),
      headerScopes: [...first.querySelectorAll('th')].map((th) => th.getAttribute('scope'))
    };
  })()`);
  check(rows.seq.length > 0 && rows.seq[0] === `1/${rows.seq.length}`,
    'first row is numbered 1 of N', `first=${rows.seq[0]} count=${rows.seq.length}`);
  check(rows.links.every((l) => l.href.startsWith('https://www.youtube.com/watch?v=')),
    'every link points at a YouTube watch URL');
  check(rows.links.every((l) => l.rel === 'noopener noreferrer' && l.target === '_blank'),
    'links open in a new tab without leaking the referrer');
  check(rows.caption !== null && /in watch order/.test(rows.caption),
    'table has a description for screen readers', rows.caption ?? 'none');
  check(rows.captionHidden === true,
    'that description is visually hidden but still in the accessibility tree');
  check(rows.headerScopes.every((scope) => scope === 'col'),
    'all column headers declare scope="col"');

  // --- 4. keyboard ---------------------------------------------------------

  section('4. Keyboard operation');
  await evaluate(`(() => {
    const q = document.getElementById('q');
    q.value = '';
    q.dispatchEvent(new Event('input', { bubbles: true }));
    q.focus();
  })()`);
  // Tab from the search box; the first topic button should take focus.
  await send('Input.dispatchKeyEvent', { type: 'keyDown', key: 'Tab', code: 'Tab', windowsVirtualKeyCode: 9 });
  await send('Input.dispatchKeyEvent', { type: 'keyUp', key: 'Tab', code: 'Tab', windowsVirtualKeyCode: 9 });
  const focused = await evaluate(`({
    tag: document.activeElement.tagName,
    text: document.activeElement.textContent.trim(),
    label: document.activeElement.getAttribute('aria-label')
  })`);
  check(focused.tag === 'BUTTON', `Tab reaches a topic control (focused <${focused.tag.toLowerCase()}>)`,
    focused.text);
  check(/^Search for .+, \d+ videos$/.test(focused.label ?? ''),
    'that control announces itself', focused.label ?? 'no aria-label');

  // Activate it with the keyboard, the way a real button responds to Enter.
  await send('Input.dispatchKeyEvent', {
    type: 'keyDown', key: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13, text: '\r'
  });
  await send('Input.dispatchKeyEvent', {
    type: 'keyUp', key: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13
  });
  await delay(100);
  const afterEnter = await evaluate(`({
    query: document.getElementById('q').value,
    results: document.querySelectorAll('#results .group').length,
    focusIsSearchBox: document.activeElement.id === 'q'
  })`);
  check(afterEnter.results > 0, 'Enter runs the search', `query="${afterEnter.query}"`);
  check(afterEnter.focusIsSearchBox, 'focus moves to the search box so the query can be narrowed');

  const focusRing = await evaluate(`(() => {
    const button = document.querySelector('#topics button');
    button.focus();
    const style = getComputedStyle(button);
    return { width: style.outlineWidth, style: style.outlineStyle, color: style.outlineColor };
  })()`);
  check(focusRing.style !== 'none' && parseFloat(focusRing.width) >= 2,
    'focused controls show a visible focus ring',
    `${focusRing.width} ${focusRing.style} ${focusRing.color}`);

  section('5. Empty and no-match states');
  const states = await evaluate(`(() => {
    const q = document.getElementById('q');
    const set = (value) => { q.value = value; q.dispatchEvent(new Event('input', { bubbles: true })); };
    set('zzzqqq');
    const noMatch = {
      status: document.getElementById('status').textContent,
      results: document.querySelectorAll('#results .group').length
    };
    set('');
    const cleared = {
      status: document.getElementById('status').textContent,
      topics: document.querySelectorAll('#topics button').length
    };
    return { noMatch, cleared };
  })()`);
  check(states.noMatch.results === 0 && /No matching sequences/.test(states.noMatch.status),
    'a no-match search clears results and says so', states.noMatch.status);
  check(states.cleared.topics === 40 && /Type a search term/.test(states.cleared.status),
    'clearing the box restores all 40 topics', states.cleared.status);

  // --- 6. contrast --------------------------------------------------------

  section('6. WCAG AA contrast, from computed styles');
  await evaluate(`(() => {
    const q = document.getElementById('q');
    q.value = 'sandhyavandana';
    q.dispatchEvent(new Event('input', { bubbles: true }));
  })()`);

  const contrast = await evaluate(`(() => {
    const parse = (value) => {
      const nums = value.match(/[\\d.]+/g);
      if (!nums) return null;
      const [r, g, b, a] = nums.map(Number);
      return { r, g, b, a: a === undefined ? 1 : a };
    };
    // WCAG relative luminance.
    const luminance = ({ r, g, b }) => {
      const channel = (v) => {
        const s = v / 255;
        return s <= 0.03928 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
      };
      return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
    };
    const ratio = (a, b) => {
      const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
      return (hi + 0.05) / (lo + 0.05);
    };
    // The background actually behind an element: walk up until something opaque.
    const backgroundOf = (element) => {
      for (let node = element; node; node = node.parentElement) {
        const colour = parse(getComputedStyle(node).backgroundColor);
        if (colour && colour.a > 0) return colour;
      }
      return { r: 255, g: 255, b: 255, a: 1 };
    };

    const results = [];
    for (const element of document.querySelectorAll('body *')) {
      // Only elements rendering their own visible text.
      const ownText = [...element.childNodes]
        .filter((n) => n.nodeType === Node.TEXT_NODE)
        .map((n) => n.textContent.trim()).join('');
      if (!ownText) continue;
      const box = element.getBoundingClientRect();
      if (box.width <= 1 || box.height <= 1) continue;   // visually hidden

      const style = getComputedStyle(element);
      if (style.visibility === 'hidden' || style.display === 'none') continue;

      const size = parseFloat(style.fontSize);
      const weight = Number(style.fontWeight) || 400;
      // WCAG "large text": 18.66px+ bold, or 24px+ at any weight.
      const isLarge = size >= 24 || (size >= 18.66 && weight >= 700);
      const required = isLarge ? 3 : 4.5;

      results.push({
        selector: element.tagName.toLowerCase() + (element.className ? '.' + String(element.className).split(' ')[0] : ''),
        sample: ownText.slice(0, 34),
        colour: style.color,
        background: (() => { const b = backgroundOf(element); return \`rgb(\${b.r}, \${b.g}, \${b.b})\`; })(),
        size, weight, isLarge, required,
        ratio: Math.round(ratio(parse(style.color), backgroundOf(element)) * 100) / 100
      });
    }
    return results;
  })()`);

  const worst = new Map();
  for (const entry of contrast) {
    const key = `${entry.selector}|${entry.colour}|${entry.background}|${entry.size}|${entry.weight}`;
    if (!worst.has(key) || worst.get(key).ratio > entry.ratio) worst.set(key, entry);
  }
  const unique = [...worst.values()].sort((a, b) => a.ratio - b.ratio);

  console.log(`  Measured ${contrast.length} text-bearing elements, ${unique.length} distinct colour/size pairs.\n`);
  console.log('  ratio  need  size/weight  element              colour on background');
  console.log('  -----  ----  -----------  -------------------  ---------------------------------');
  for (const entry of unique) {
    const flag = entry.ratio >= entry.required ? ' ' : '<';
    console.log(
      `  ${entry.ratio.toFixed(2).padStart(5)}${flag} ${entry.required.toFixed(1).padStart(4)}  ` +
      `${String(entry.size + 'px/' + entry.weight).padEnd(11)}  ${entry.selector.padEnd(19)}  ` +
      `${entry.colour} on ${entry.background}`
    );
  }
  console.log();

  const failing = unique.filter((entry) => entry.ratio < entry.required);
  check(failing.length === 0, `every text colour meets its WCAG AA threshold`,
    failing.map((f) => `${f.selector} ${f.ratio} < ${f.required} (${f.colour} on ${f.background})`).join('; '));

  const aaa = unique.filter((entry) => entry.ratio < (entry.isLarge ? 4.5 : 7));
  console.log(`  (For reference: ${unique.length - aaa.length} of ${unique.length} pairs also clear the stricter AAA threshold.)`);

  // --- 7. layout ----------------------------------------------------------

  section('7. Layout');
  for (const width of [1200, 768, 375]) {
    await send('Emulation.setDeviceMetricsOverride', {
      width, height: 900, deviceScaleFactor: 1, mobile: width < 500
    });
    await delay(80);
    const layout = await evaluate(`({
      horizontalOverflow: document.documentElement.scrollWidth > window.innerWidth + 1,
      scrollWidth: document.documentElement.scrollWidth,
      innerWidth: window.innerWidth,
      searchBoxVisible: document.getElementById('q').getBoundingClientRect().width > 0
    })`);
    check(!layout.horizontalOverflow, `no horizontal overflow at ${width}px`,
      `scrollWidth=${layout.scrollWidth} viewport=${layout.innerWidth}`);
    check(layout.searchBoxVisible, `search box is usable at ${width}px`);
  }
  await send('Emulation.clearDeviceMetricsOverride');

  section('8. Screenshot');
  const shot = await send('Page.captureScreenshot', { format: 'png' });
  const shotPath = join(tmpdir(), 'search-page.png');
  await (await import('node:fs/promises')).writeFile(shotPath, Buffer.from(shot.data, 'base64'));
  check(shot.data.length > 1000, 'page renders to a non-blank screenshot', shotPath);

} finally {
  await cleanup();
}

console.log(`\n${checks - failures}/${checks} checks passed.`);
process.exit(failures === 0 ? 0 : 1);
