"use strict";
// Test-only. Runs the console page's script under node with a minimal DOM.
//   node page-harness.js <page.html>   (JSON list of steps on stdin)
// Steps: frame, open, snapshot, and the focus clock: a first-only start
// {focused, clock}, then clock, focus, blur, hide, pagehide. The owner's
// answer adds {key, ctrlKey?, altKey?, metaKey?, target?} (a keydown on the
// document; target is the tag name of the focused element, default none),
// {stream_break: true} and {stream_open: true} call the stream's onerror and onopen,
// follow: true (the target is the focused element, else a BODY as a browser reports),
// {click: "<class>"} (the click listeners of the first attached element with
// that class; none throws), {respond: {status, text}} (queues the answer of
// the next fetch but /api/looked, default 204 with no text) and
// {fail_fetch: true} (the next such fetch rejects; /api/answer and
// /api/check-answer take the queued replies like the goal routes). {hold: true}
// makes the next such fetch stay pending until a later {release: {status, text}}
// answers the oldest held fetch (release with none held throws). The key step
// also accepts editable: true, which gives the target isContentEditable. The
// fake controls hold a value, a disabled flag, a selection and focus:
// {type: {class, text}} focuses the first attached element with that class,
// sets its value to the text (an INPUT drops every CR and LF, a TEXTAREA turns
// CRLF and CR into LF), puts the selection at the end and fires its input
// listeners; {append: {class, text}} does the same on top of the current
// value. The goal field adds {input: {cls, value}} (the first attached element
// with that class gets .value, then its input listeners run with {type:
// "input", target}; none throws) and {focus_on: "<class>"} (calls .focus() on
// the first attached element with that class; none throws; {focus: true} stays
// the window's focus). {select: {cls, start, end}} sets the selection of the
// first attached element with that class (none throws); {input} also puts the
// caret at the end of the value. Elem.focus() sets state.active, counts in
// state.focusCount and, only when the element was not already active, fires its
// own focus listeners with {type: "focus", target}; after its disabled and inert
// checks Elem.focus() also adds 1 to state.hiddenFocus (the snapshot's
// hidden_focus, starting at 0) when an ancestor DETAILS is not open and the
// element is not inside that details' own SUMMARY child, and focuses all the same; Elem.focus(options) also adds 1 to
// state.scrollingFocus (the snapshot's scrolling_focus) unless options.preventScroll is true, as a browser scrolls a
// focused element into view only then; Elem.blur() clears
// state.active when it is that element and fires nothing; removing a node (replaceChildren dropping it, appendChild
// moving it, the textContent setter, Elem.remove()) clears state.active when it
// is that node or inside its subtree, as a browser blurs a removed element, and
// document.activeElement is state.active only while attached. A snapshot adds
// field: {cls, value, start, end} of the attached active element when it has a
// value, else null. A key step records in state.keyPrevented whether its event
// had preventDefault called (null before any key step). A click step skips a
// disabled element. The fake setTimeout/clearTimeout fire when a clock step
// reaches their due time. Each step settles pending promises before the next. A snapshot holds the trees
// of the inbox, statement, projects, unmanaged, register, digest, goal, capacity,
// pool, promoted and reading sections; every serialized node carries its title attribute (null
// when unset), which is where a time element keeps its exact local time, and
// its placeholder attribute (null when unset) and its inline style.width (null
// when unset; Elem.style is a plain object) and its aria-label attribute as
// label (null when unset) and, on an A element, its href (null when unset or
// empty). {close: "<details key>"} sets that fold's open to
// false (none throws), the mirror of open. Both fire the fold's toggle listeners. An optional "in": "<details key>" on
// a click, type, append, input, select or focus_on step limits the lookup to the
// first attached element with the class inside that fold's subtree (an unknown
// key or no match throws); without it the lookup is unchanged. A key step may
// carry "on": "<class>": its target is then the first attached element with
// that class (none throws), its own keydown listeners run first and then the
// document's, with one event {key, ctrlKey, altKey, metaKey, shiftKey: false,
// repeat: false, target: <element>, preventDefault()}. {blur_on: "<class>",
// to?: "<class>"} calls the element's blur() and fires its blur listeners with
// {type: "blur", target, relatedTarget}, relatedTarget being the first attached
// element with the to class, else null. When a removal clears state.active
// (remove, appendChild moving it, replaceChildren, textContent) the removed
// active element's blur listeners then fire with relatedTarget null, as an
// engine blurs a removed element.
// The markup's tags with an id are parsed with their class attribute (className), every
// other name="value" attribute (attributes) and a bare hidden (hidden); an Elem holds hidden
// and an isConnected getter (true when its parentNode chain reaches the root). A snapshot
// node carries hidden (bool) and expanded (its aria-expanded attribute, null when unset), and
// the snapshot adds accounts and accounts_body (each a node or null) beside account_add, and sharing, sharing_body and sharing_open the same way,
// and spend_link (#spend-link) and top_who (#top-who) likewise. A {snapshot: "page"} step also adds page: the node() tree of every
// non-text child of root (each id'd element, as the markup makes them all direct children), else page is null.
// A fetch of a URL starting /api/picture/ is answered by the harness itself: it is recorded
// in posts like every fetch but never takes from the replies queue or a hold, and answers
// {status, ok, text(), blob()} with the status of the latest {picture_reply: {id, status}}
// step for that id (default 200) and a blob() that resolves to {picture: id}. A URL global
// has createObjectURL(blob), which returns "blob:console/" + n (n from 1) and records
// {url, picture: blob.picture} in made, and revokeObjectURL(url), which records url in
// revoked. A snapshot node adds src (an IMG's src property, else null) and alt (its alt
// attribute, else null), and the snapshot adds viewer (the #viewer node or null) and
// object_urls: {made, revoked}. A click, focus_on or key step's "on" takes an optional
// nth (0-based, default 0) choosing among the matches in document order; fewer matches
// throw.
// {check: {cls, checked, nth?}} toggles a checkbox as a browser does: the nth (default 0) attached element with
// the class, when it is not disabled, gets .checked set to the given boolean and its change listeners run with
// {type: "change", target}; a disabled one is left alone; none throws. A click step stays a listener call with no
// native activation, so it never toggles a checkbox. The snapshot adds own_account (#own-account, or null) beside
// pool.
// Elem.removeAttribute(name) deletes the attribute and, for disabled, sets .disabled to false.
// A snapshot node adds busy (its aria-busy attribute, null when unset) and aria_disabled (its
// aria-disabled attribute, null when unset); disabled stays the native flag only.
// A key step also takes shiftKey (default false) and passes it on the event. document.body is
// root, whose direct children are the page's id'd elements (#viewer among them). A snapshot
// node adds inert (true only when the element's inert property is true), and Elem.focus() does
// nothing when the element or any ancestor through parentNode has inert true, as a browser
// refuses focus inside an inert subtree. The harness still performs no native activation and no
// native focus move: a key never clicks the focused button and Tab never moves focus by itself;
// both are checked in a browser.
// window has scrollY (default 0) and scrollTo(x, y), which sets scrollY to y; a {scroll: y}
// step sets scrollY as the owner scrolling would, and a snapshot adds scroll_y.
// Prints a JSON list of snapshots on stdout; any failure exits 1 with the
// error on stderr. A selector the fake DOM does not support throws, so a
// test cannot pass on a stub.
const fs = require("fs");
const vm = require("vm");

class Text {
  constructor(text) {
    this.isText = true;
    this.text = text;
    this.parentNode = null;
  }
}

function loseFocus(removed) {
  const was = state.active;
  for (let n = was; n; n = n.parentNode) {
    if (n === removed) {
      state.active = null;
      for (const fn of was.listeners.blur || []) fn({ type: "blur", target: was, relatedTarget: null });
      return;
    }
  }
}

class Elem {
  constructor(tag) {
    this.tagName = tag.toUpperCase();
    this.className = "";
    this.id = "";
    this.dataset = {};
    this.attributes = {};
    this.style = {};
    this.listeners = {};
    this.open = false;
    this.value = "";
    this.disabled = false;
    this.hidden = false;
    this.selectionStart = 0;
    this.selectionEnd = 0;
    this.children = [];
    this.parentNode = null;
  }
  remove() {
    if (!this.parentNode) return;
    loseFocus(this);
    this.parentNode.children = this.parentNode.children.filter((c) => c !== this);
    this.parentNode = null;
  }
  addEventListener(name, fn) {
    (this.listeners[name] = this.listeners[name] || []).push(fn);
  }
  setAttribute(name, value) {
    this.attributes[name] = String(value);
    if (name === "disabled") this.disabled = true;
  }
  removeAttribute(name) {
    delete this.attributes[name];
    if (name === "disabled") this.disabled = false;
  }
  focus(options) {
    if (this.disabled === true) return; // a browser does not focus a disabled control
    for (let n = this; n; n = n.parentNode) if (n.inert === true) return; // nor inside an inert subtree
    for (let n = this; n.parentNode; n = n.parentNode) {
      const up = n.parentNode;
      if (up.tagName === "DETAILS" && up.open !== true && n.tagName !== "SUMMARY") {
        state.hiddenFocus += 1; // a browser does not focus a control in a closed details
        break;
      }
    }
    const was = state.active === this;
    state.active = this;
    state.focusCount += 1;
    if (!(options && options.preventScroll === true)) state.scrollingFocus += 1; // a browser scrolls the element into view
    if (!was) for (const fn of this.listeners.focus || []) fn({ type: "focus", target: this });
  }
  blur() {
    if (state.active === this) state.active = null;
  }
  setSelectionRange(start, end) {
    this.selectionStart = start;
    this.selectionEnd = end;
  }
  get isConnected() {
    for (let n = this; n; n = n.parentNode) if (n === root) return true;
    return false;
  }
  get firstElementChild() {
    return this.children.find((c) => !c.isText) || null;
  }
  _adopt(node) {
    if (node.parentNode) {
      loseFocus(node);
      node.parentNode.children = node.parentNode.children.filter((c) => c !== node);
    }
    node.parentNode = this;
  }
  appendChild(node) {
    this._adopt(node);
    this.children.push(node);
    return node;
  }
  replaceChildren(...nodes) {
    for (const old of this.children) {
      loseFocus(old);
      old.parentNode = null;
    }
    this.children = [];
    for (const node of nodes) this.appendChild(node);
  }
  cloneNode(deep) {
    const copy = new Elem(this.tagName);
    copy.className = this.className;
    copy.id = this.id;
    copy.dataset = Object.assign({}, this.dataset);
    copy.open = this.open;
    if (deep) {
      for (const child of this.children) {
        copy.appendChild(child.isText ? new Text(child.text) : child.cloneNode(true));
      }
    }
    return copy;
  }
  get textContent() {
    return this.children.map((c) => (c.isText ? c.text : c.textContent)).join("");
  }
  set textContent(value) {
    this.replaceChildren(new Text(String(value)));
  }
}

const COMPOUND = /^([a-zA-Z][a-zA-Z0-9]*)?((?:#[\w-]+|\.[\w-]+|\[open\])*)$/;

function parseSelector(selector) {
  const parts = selector.trim().split(/\s+/);
  return parts.map((part) => {
    const m = COMPOUND.exec(part);
    if (!m || part === "") throw new Error("unsupported selector: " + selector);
    const compound = { tag: m[1] ? m[1].toUpperCase() : null, id: null, classes: [], open: false };
    for (const token of m[2].match(/#[\w-]+|\.[\w-]+|\[open\]/g) || []) {
      if (token[0] === "#") compound.id = token.slice(1);
      else if (token[0] === ".") compound.classes.push(token.slice(1));
      else compound.open = true;
    }
    return compound;
  });
}

function matches(node, c) {
  if (c.tag && node.tagName !== c.tag) return false;
  if (c.id && node.id !== c.id) return false;
  const have = node.className.split(/\s+/);
  if (!c.classes.every((k) => have.includes(k))) return false;
  if (c.open && node.open !== true) return false;
  return true;
}

function matchesChain(node, chain, index) {
  if (!matches(node, chain[index])) return false;
  if (index === 0) return true;
  for (let up = node.parentNode; up; up = up.parentNode) {
    if (matchesChain(up, chain, index - 1)) return true;
  }
  return false;
}

function attached(root) {
  const out = [];
  const walk = (node) => {
    for (const child of node.children) {
      if (child.isText) continue;
      out.push(child);
      walk(child);
    }
  };
  walk(root);
  return out;
}

const pagePath = process.argv[2];
const html = fs.readFileSync(pagePath, "utf8");
const open = html.indexOf("<script>");
const close = html.lastIndexOf("</script>");
if (open < 0 || close < 0) throw new Error("the page has no script");
const script = html.slice(open + "<script>".length, close);
const markup = html.slice(0, open) + html.slice(close);

const root = new Elem("html");
const templates = new Map();
for (const m of markup.matchAll(/<([a-zA-Z][a-zA-Z0-9]*)\b([^>]*?\bid="([^"]+)"[^>]*)>/g)) {
  const node = new Elem(m[1]);
  node.id = m[3];
  const given = /\bclass="([^"]*)"/.exec(m[2]);
  if (given) node.className = given[1];
  for (const a of m[2].matchAll(/([\w-]+)="([^"]*)"/g)) {
    if (a[1] !== "class" && a[1] !== "id") node.attributes[a[1]] = a[2];
  }
  if (/(^|\s)hidden(\s|$)/.test(m[2].replace(/="[^"]*"/g, '=""'))) node.hidden = true;
  const withContent = /\bcontent="([^"]*)"/.exec(m[2]);
  if (withContent) node.content = withContent[1];
  if (m[1] === "template") {
    templates.set(node.id, node);
    node.content = new Elem("fragment");
    node.content.appendChild(new Elem("svg"));
  } else {
    root.appendChild(node);
  }
}

const steps = JSON.parse(fs.readFileSync(0, "utf8"));
const state = {
  focused: false, visibility: "visible", clock: null, active: null, focusCount: 0, scrollingFocus: 0, hiddenFocus: 0, keyPrevented: null,
};
if (steps.length > 0 && "start" in steps[0]) {
  state.focused = steps[0].start.focused;
  state.clock = steps[0].start.clock;
  steps.shift();
}

class HarnessDate extends Date {
  static now() {
    return state.clock === null ? Date.now() : state.clock;
  }
}

const listeners = { window: {}, document: {} };
function listen(target) {
  return (name, fn) => {
    (listeners[target][name] = listeners[target][name] || []).push(fn);
  };
}
function fire(target, name, extra) {
  for (const fn of listeners[target][name] || []) fn(Object.assign({ type: name }, extra));
}
const window = { addEventListener: listen("window"), scrollY: 0, scrollTo(x, y) { this.scrollY = y; } };
const posts = [];
const replies = [];
const held = [];
const pictureStatus = new Map();
const object_urls = { made: [], revoked: [] };
const URL = {
  createObjectURL(blob) {
    const url = "blob:console/" + (object_urls.made.length + 1);
    object_urls.made.push({ url, picture: blob.picture });
    return url;
  },
  revokeObjectURL(url) {
    object_urls.revoked.push(url);
  },
};
function fetch(url, options) {
  const post = {
    url, method: options.method, headers: options.headers, keepalive: options.keepalive,
  };
  if (options.body !== undefined) post.body = options.body;
  posts.push(post);
  if (url.startsWith("/api/picture/")) {
    const id = url.slice("/api/picture/".length);
    const status = pictureStatus.has(id) ? pictureStatus.get(id) : 200;
    return Promise.resolve({
      status, ok: status >= 200 && status < 300,
      text: () => Promise.resolve(""), blob: () => Promise.resolve({ picture: id }),
    });
  }
  if (url === "/api/looked") return Promise.resolve({});
  const reply = replies.length > 0 ? replies.shift() : { status: 204, text: "" };
  if (reply.reject) return Promise.reject(new Error("the console did not answer"));
  if (reply.hold) return new Promise((resolve) => held.push(resolve));
  return Promise.resolve(answer(reply));
}
function answer(reply) {
  return {
    status: reply.status, ok: reply.status >= 200 && reply.status < 300,
    text: () => Promise.resolve(reply.text),
  };
}

const timers = new Map();
let nextTimer = 1;
function setTimeout(fn, ms) {
  const id = nextTimer++;
  timers.set(id, { fn, due: HarnessDate.now() + ms });
  return id;
}
function clearTimeout(id) {
  timers.delete(id);
}
function runDueTimers() {
  for (;;) {
    let next = null;
    for (const [id, timer] of timers) {
      if (timer.due <= HarnessDate.now() && (next === null || timer.due < timers.get(next).due)) next = id;
    }
    if (next === null) return;
    const { fn } = timers.get(next);
    timers.delete(next);
    fn();
  }
}
const settle = async () => {
  for (let i = 0; i < 5; i++) await new Promise((r) => setImmediate(r));
};

const document = {
  addEventListener: listen("document"),
  hasFocus: () => state.focused,
  body: root,
  get activeElement() {
    return state.active && attached(root).includes(state.active) ? state.active : null;
  },
  get visibilityState() {
    return state.visibility;
  },
  createElement: (tag) => new Elem(tag),
  getElementById(id) {
    if (templates.has(id)) return templates.get(id);
    return attached(root).find((n) => n.id === id) || null;
  },
  querySelectorAll(selector) {
    const chain = parseSelector(selector);
    return attached(root).filter((n) => matchesChain(n, chain, chain.length - 1));
  },
  querySelector(selector) {
    return this.querySelectorAll(selector)[0] || null;
  },
};

const sources = [];
class EventSource {
  constructor(url) {
    this.url = url;
    this.listeners = {};
    sources.push(this);
  }
  addEventListener(name, fn) {
    this.listeners[name] = fn;
  }
}

vm.runInNewContext(script, {
  document, window, fetch, EventSource, Date: HarnessDate, JSON, String, Math, Number, Array, Object, console,
  setTimeout, clearTimeout, URL,
});

function node(n) {
  return {
    tag: n.tagName.toLowerCase(),
    cls: n.className,
    src: n.tagName === "IMG" && n.src !== undefined ? n.src : null,
    alt: n.attributes.alt === undefined ? null : n.attributes.alt,
    key: n.dataset.key === undefined ? null : n.dataset.key,
    title: n.attributes.title === undefined ? null : n.attributes.title,
    placeholder: n.attributes.placeholder === undefined ? null : n.attributes.placeholder,
    href: n.tagName === "A" && n.href ? n.href : null,
    label: n.attributes["aria-label"] === undefined ? null : n.attributes["aria-label"],
    width: n.style.width === undefined ? null : n.style.width,
    open: n.open,
    hidden: n.hidden === true,
    inert: n.inert === true,
    expanded: n.attributes["aria-expanded"] === undefined ? null : n.attributes["aria-expanded"],
    pressed: n.attributes["aria-pressed"] === undefined ? null : n.attributes["aria-pressed"],
    busy: n.attributes["aria-busy"] === undefined ? null : n.attributes["aria-busy"],
    aria_disabled: n.attributes["aria-disabled"] === undefined ? null : n.attributes["aria-disabled"],
    value: n.value === undefined ? null : n.value,
    disabled: n.disabled === true || "disabled" in n.attributes,
    text: n.children.filter((c) => c.isText).map((c) => c.text).join(""),
    value: n.tagName === "INPUT" || n.tagName === "TEXTAREA" ? n.value : null,
    selection: n.tagName === "INPUT" || n.tagName === "TEXTAREA" ? [n.selectionStart, n.selectionEnd] : null,
    disabled: n.disabled === true,
    focused: n === document.activeElement,
    children: n.children.filter((c) => !c.isText).map(node),
  };
}

function typeInto(spec, append, scope) {
  const target = attached(scope).find((n) => n.className.split(/\s+/).includes(spec.class));
  if (!target) throw new Error("no element with class " + spec.class);
  const text = target.tagName === "INPUT"
    ? spec.text.replace(/[\r\n]/g, "")
    : spec.text.replace(/\r\n?/g, "\n");
  target.focus();
  target.value = append ? target.value + text : text;
  target.selectionStart = target.value.length;
  target.selectionEnd = target.value.length;
  for (const fn of target.listeners.input || []) fn({ type: "input", target });
}


function scopeOf(step) {
  if (step.in === undefined) return root;
  const fold = attached(root).find((n) => n.tagName === "DETAILS" && n.dataset.key === step.in);
  if (!fold) throw new Error("no details with key " + step.in);
  return fold;
}

function byClass(cls, scope, nth = 0) {
  const found = attached(scope).filter((n) => n.className.split(/\s+/).includes(cls))[nth];
  if (!found) throw new Error("no element with class " + cls + " at " + nth);
  return found;
}

const snapshots = [];
async function run() {
  for (const step of steps) {
    if ("frame" in step) {
      const listener = sources[0] && sources[0].listeners.view;
      if (!listener) throw new Error("the page registered no view listener");
      listener({ data: JSON.stringify(step.frame) });
    } else if ("open" in step) {
      const fold = attached(root).find((n) => n.tagName === "DETAILS" && n.dataset.key === step.open);
      if (!fold) throw new Error("no details with key " + step.open);
      fold.open = true;
      for (const fn of fold.listeners.toggle || []) fn({ type: "toggle", target: fold });
    } else if ("close" in step) {
      const fold = attached(root).find((n) => n.tagName === "DETAILS" && n.dataset.key === step.close);
      if (!fold) throw new Error("no details with key " + step.close);
      fold.open = false;
      for (const fn of fold.listeners.toggle || []) fn({ type: "toggle", target: fold });
    } else if ("stream_break" in step) {
      sources[0].onerror();
    } else if ("stream_open" in step) {
      sources[0].onopen();
    } else if ("clock" in step) {
      state.clock = step.clock;
      runDueTimers();
    } else if ("key" in step) {
      let prevented = false;
      const own = step.on === undefined ? null : byClass(step.on, root, step.nth);
      const event = {
        key: step.key, ctrlKey: !!step.ctrlKey, altKey: !!step.altKey, metaKey: !!step.metaKey,
        shiftKey: step.shiftKey === true, repeat: false, preventDefault() { prevented = true; },
        target: own !== null ? own
          : step.follow === true ? (document.activeElement || { tagName: "BODY", isContentEditable: false })
          : step.target === undefined ? null : { tagName: step.target, isContentEditable: step.editable === true },
      };
      if (own !== null) for (const fn of own.listeners.keydown || []) fn(Object.assign({ type: "keydown" }, event));
      fire("document", "keydown", event);
      state.keyPrevented = prevented;
    } else if ("blur_on" in step) {
      const target = byClass(step.blur_on, root);
      const related = step.to === undefined ? null : byClass(step.to, root);
      target.blur();
      for (const fn of target.listeners.blur || []) fn({ type: "blur", target, relatedTarget: related });
    } else if ("click" in step) {
      const target = byClass(step.click, scopeOf(step), step.nth);
      if (target.disabled !== true) {
        for (const fn of target.listeners.click || []) fn({ type: "click", preventDefault() {}, stopPropagation() {} });
      }
    } else if ("check" in step) {
      const target = byClass(step.check.cls, scopeOf(step), step.check.nth);
      if (target.disabled !== true) {
        target.checked = step.check.checked === true;
        for (const fn of target.listeners.change || []) fn({ type: "change", target });
      }
    } else if ("type" in step) {
      typeInto(step.type, false, scopeOf(step));
    } else if ("append" in step) {
      typeInto(step.append, true, scopeOf(step));
    } else if ("input" in step) {
      const target = byClass(step.input.cls, scopeOf(step));
      target.value = step.input.value;
      target.selectionStart = target.selectionEnd = target.value.length;
      for (const fn of target.listeners.input || []) fn({ type: "input", target });
    } else if ("select" in step) {
      byClass(step.select.cls, scopeOf(step)).setSelectionRange(step.select.start, step.select.end);
    } else if ("scroll" in step) {
      window.scrollY = step.scroll;
    } else if ("focus_on" in step) {
      byClass(step.focus_on, scopeOf(step), step.nth).focus();
    } else if ("picture_reply" in step) {
      pictureStatus.set(step.picture_reply.id, step.picture_reply.status);
    } else if ("respond" in step) {
      replies.push(step.respond);
    } else if ("fail_fetch" in step) {
      replies.push({ reject: true });
    } else if ("hold" in step) {
      replies.push({ hold: true });
    } else if ("release" in step) {
      if (held.length === 0) throw new Error("no held fetch to release");
      held.shift()(answer({ status: 204, text: "", ...step.release }));
    } else if (step.focus) {
      state.focused = true;
      fire("window", "focus");
    } else if (step.blur) {
      state.focused = false;
      fire("window", "blur");
    } else if (step.hide) {
      state.visibility = "hidden";
      fire("document", "visibilitychange");
    } else if (step.pagehide) {
      fire("window", "pagehide");
    } else if (step.snapshot) {
      const byId = (id) => root.children.find((n) => n.id === id) || null;
      const unmanaged = byId("unmanaged");
      const field = document.activeElement;
      snapshots.push({
        inbox: byId("inbox") ? node(byId("inbox")) : null,
        statement: byId("statement") ? node(byId("statement")) : null,
        projects: node(byId("projects")),
        unmanaged: unmanaged ? node(unmanaged) : null,
        digest: byId("digest") ? node(byId("digest")) : null,
        goal: byId("goal") ? node(byId("goal")) : null,
        capacity: byId("capacity") ? node(byId("capacity")) : null,
        pool: byId("pool") ? node(byId("pool")) : null,
        own_account: byId("own-account") ? node(byId("own-account")) : null,
        account_add: byId("account-add") ? node(byId("account-add")) : null,
        register: byId("register") ? node(byId("register")) : null,
        accounts: byId("accounts") ? node(byId("accounts")) : null,
        accounts_body: byId("accounts-body") ? node(byId("accounts-body")) : null,
        sharing: byId("sharing") ? node(byId("sharing")) : null,
        sharing_body: byId("sharing-body") ? node(byId("sharing-body")) : null,
        sharing_open: byId("sharing-open") ? node(byId("sharing-open")) : null,
        spend_link: byId("spend-link") ? node(byId("spend-link")) : null,
        top_who: byId("top-who") ? node(byId("top-who")) : null,
        page: step.snapshot === "page"
          ? { tag: "page", cls: "", text: "", children: root.children.filter((c) => !c.isText).map(node) } : null,
        promoted: byId("promoted") ? node(byId("promoted")) : null,
        reading: byId("reading") ? node(byId("reading")) : null,
        viewer: byId("viewer") ? node(byId("viewer")) : null,
        object_urls: { made: object_urls.made.slice(), revoked: object_urls.revoked.slice() },
        active: state.active && attached(root).includes(state.active) ? state.active.className : null,
        field: field === null || (field.tagName !== "INPUT" && field.tagName !== "TEXTAREA") ? null : {
          cls: field.className, value: field.value, start: field.selectionStart,
          end: field.selectionEnd,
        },
        focus_count: state.focusCount,
        scrolling_focus: state.scrollingFocus,
        hidden_focus: state.hiddenFocus,
        scroll_y: window.scrollY,
        key_prevented: state.keyPrevented,
        posts: posts.slice(),
      });
    } else {
      throw new Error("unknown step " + JSON.stringify(step));
    }
    await settle();
  }
}
run().then(
  () => process.stdout.write(JSON.stringify(snapshots)),
  (error) => {
    process.stderr.write(String(error && error.stack ? error.stack : error) + "\n");
    process.exit(1);
  },
);
