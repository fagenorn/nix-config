"use strict";
// Test-only. Runs the console page's script under node with a minimal DOM.
//   node page-harness.js <page.html>   (JSON list of steps on stdin)
// Steps: frame, open, snapshot, and the focus clock: a first-only start
// {focused, clock}, then clock, focus, blur, hide, pagehide. The owner's
// answer adds {key, ctrlKey?, altKey?, metaKey?, target?} (a keydown on the
// document; target is the tag name of the focused element, default none),
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
// own focus listeners with {type: "focus", target}; Elem.blur() clears
// state.active when it is that element and fires nothing; removing a node (replaceChildren dropping it, appendChild
// moving it, the textContent setter, Elem.remove()) clears state.active when it
// is that node or inside its subtree, as a browser blurs a removed element, and
// document.activeElement is state.active only while attached. A snapshot adds
// field: {cls, value, start, end} of the attached active element when it has a
// value, else null. A key step records in state.keyPrevented whether its event
// had preventDefault called (null before any key step). A click step skips a
// disabled element. The fake setTimeout/clearTimeout fire when a clock step
// reaches their due time. Each step settles pending promises before the next. A snapshot holds the trees
// of the inbox, statement, projects, unmanaged, digest, goal, capacity and
// promoted sections; every serialized node carries its title attribute (null
// when unset), which is where a time element keeps its exact local time, and
// its placeholder attribute (null when unset) and its inline style.width (null
// when unset; Elem.style is a plain object) and its aria-label attribute as
// label (null when unset) and, on an A element, its href (null when unset or
// empty). {close: "<details key>"} sets that fold's open to
// false (none throws), the mirror of open. An optional "in": "<details key>" on
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
  focus() {
    const was = state.active === this;
    state.active = this;
    state.focusCount += 1;
    if (!was) for (const fn of this.listeners.focus || []) fn({ type: "focus", target: this });
  }
  blur() {
    if (state.active === this) state.active = null;
  }
  setSelectionRange(start, end) {
    this.selectionStart = start;
    this.selectionEnd = end;
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
  focused: false, visibility: "visible", clock: null, active: null, focusCount: 0, keyPrevented: null,
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
const window = { addEventListener: listen("window") };
const posts = [];
const replies = [];
const held = [];
function fetch(url, options) {
  const post = {
    url, method: options.method, headers: options.headers, keepalive: options.keepalive,
  };
  if (options.body !== undefined) post.body = options.body;
  posts.push(post);
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
  setTimeout, clearTimeout,
});

function node(n) {
  return {
    tag: n.tagName.toLowerCase(),
    cls: n.className,
    key: n.dataset.key === undefined ? null : n.dataset.key,
    title: n.attributes.title === undefined ? null : n.attributes.title,
    placeholder: n.attributes.placeholder === undefined ? null : n.attributes.placeholder,
    href: n.tagName === "A" && n.href ? n.href : null,
    label: n.attributes["aria-label"] === undefined ? null : n.attributes["aria-label"],
    width: n.style.width === undefined ? null : n.style.width,
    open: n.open,
    pressed: n.attributes["aria-pressed"] === undefined ? null : n.attributes["aria-pressed"],
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

function byClass(cls, scope) {
  const found = attached(scope).find((n) => n.className.split(/\s+/).includes(cls));
  if (!found) throw new Error("no element with class " + cls);
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
    } else if ("close" in step) {
      const fold = attached(root).find((n) => n.tagName === "DETAILS" && n.dataset.key === step.close);
      if (!fold) throw new Error("no details with key " + step.close);
      fold.open = false;
    } else if ("clock" in step) {
      state.clock = step.clock;
      runDueTimers();
    } else if ("key" in step) {
      let prevented = false;
      const own = step.on === undefined ? null : byClass(step.on, root);
      const event = {
        key: step.key, ctrlKey: !!step.ctrlKey, altKey: !!step.altKey, metaKey: !!step.metaKey,
        shiftKey: false, repeat: false, preventDefault() { prevented = true; },
        target: own !== null ? own
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
      const target = byClass(step.click, scopeOf(step));
      if (target.disabled !== true) {
        for (const fn of target.listeners.click || []) fn({ type: "click", preventDefault() {} });
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
    } else if ("focus_on" in step) {
      byClass(step.focus_on, scopeOf(step)).focus();
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
        promoted: byId("promoted") ? node(byId("promoted")) : null,
        active: state.active && attached(root).includes(state.active) ? state.active.className : null,
        field: field === null || (field.tagName !== "INPUT" && field.tagName !== "TEXTAREA") ? null : {
          cls: field.className, value: field.value, start: field.selectionStart,
          end: field.selectionEnd,
        },
        focus_count: state.focusCount,
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
