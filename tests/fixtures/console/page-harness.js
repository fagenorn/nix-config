"use strict";
// Test-only. Runs the console page's script under node with a minimal DOM.
//   node page-harness.js <page.html>   (JSON list of steps on stdin)
// Steps: frame, open, snapshot, and the focus clock: a first-only start
// {focused, clock}, then clock, focus, blur, hide, pagehide.
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

class Elem {
  constructor(tag) {
    this.tagName = tag.toUpperCase();
    this.className = "";
    this.id = "";
    this.dataset = {};
    this.open = false;
    this.children = [];
    this.parentNode = null;
  }
  get firstElementChild() {
    return this.children.find((c) => !c.isText) || null;
  }
  _adopt(node) {
    if (node.parentNode) {
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
    for (const old of this.children) old.parentNode = null;
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
let template = null;
for (const m of markup.matchAll(/<([a-zA-Z][a-zA-Z0-9]*)\b([^>]*?\bid="([^"]+)"[^>]*)>/g)) {
  const node = new Elem(m[1]);
  node.id = m[3];
  const withContent = /\bcontent="([^"]*)"/.exec(m[2]);
  if (withContent) node.content = withContent[1];
  if (m[1] === "template") {
    template = node;
    node.content = new Elem("fragment");
    node.content.appendChild(new Elem("svg"));
  } else {
    root.appendChild(node);
  }
}

const steps = JSON.parse(fs.readFileSync(0, "utf8"));
const state = { focused: false, visibility: "visible", clock: null };
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
function fire(target, name) {
  for (const fn of listeners[target][name] || []) fn({ type: name });
}
const window = { addEventListener: listen("window") };
const posts = [];
function fetch(url, options) {
  posts.push({
    url, method: options.method, headers: options.headers, keepalive: options.keepalive,
  });
  return Promise.resolve({});
}

const document = {
  addEventListener: listen("document"),
  hasFocus: () => state.focused,
  get visibilityState() {
    return state.visibility;
  },
  createElement: (tag) => new Elem(tag),
  getElementById(id) {
    if (template && template.id === id) return template;
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
});

function node(n) {
  return {
    tag: n.tagName.toLowerCase(),
    cls: n.className,
    key: n.dataset.key === undefined ? null : n.dataset.key,
    open: n.open,
    text: n.children.filter((c) => c.isText).map((c) => c.text).join(""),
    children: n.children.filter((c) => !c.isText).map(node),
  };
}

const snapshots = [];
for (const step of steps) {
  if ("frame" in step) {
    const listener = sources[0] && sources[0].listeners.view;
    if (!listener) throw new Error("the page registered no view listener");
    listener({ data: JSON.stringify(step.frame) });
  } else if ("open" in step) {
    const fold = attached(root).find((n) => n.tagName === "DETAILS" && n.dataset.key === step.open);
    if (!fold) throw new Error("no details with key " + step.open);
    fold.open = true;
  } else if ("clock" in step) {
    state.clock = step.clock;
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
    snapshots.push({
      projects: node(byId("projects")),
      unmanaged: unmanaged ? node(unmanaged) : null,
      digest: byId("digest") ? node(byId("digest")) : null,
      posts: posts.slice(),
    });
  } else {
    throw new Error("unknown step " + JSON.stringify(step));
  }
}
process.stdout.write(JSON.stringify(snapshots));
