"""What a long command's text names, for the permission card (#1621, ADR-console-105).

A permission card shows a held command verbatim. A long command (a here-document, a chain) buries what
matters: what it runs, what it writes, and what reaches outside the project. `summarize` is the pure
reader that lifts those out of the text. It decides nothing: the owner still answers the card, and the
summary is a reading aid beside the verbatim command. It imports only the standard library.

`is_long(command)`: more than `LONG_CHARS` characters or more than `LONG_LINES` lines.
`summarize(command, root)` returns, for a command that is not long, None; for text outside the grammar
below, `{"read": False}` and never a partial summary; otherwise exactly

    {"read": True, "runs": [...], "writes": [...], "outside": [...],
     "scripts": [{"program": str, "lines": int, "paths": [...]}, ...]}

`runs` are the program words as written, `writes` the written or deleted paths as written (quotes
removed), `outside` the touched paths that are not inside `root` (the normalized absolute path when it
can be placed, else the word as written), `scripts` the interpreter code and here-documents, in text
order. Every list is in first-seen order without duplicates. With no absolute `root` every path is
outside.

The grammar it reads, one left-to-right pass. Blanks are space and tab (a backslash before a newline is
one); a `#` that begins a word starts a comment. Separators are newline, `;`, `&&`, `||`, `|`, `|&` and
`&`. Words are unquoted runs, `'...'` and `"..."`. Redirections are `>`, `>>`, `>|`, `<`, `<>`, `<<`,
`<<-`, `<<<`, `>&`, `<&`, `&>` and `&>>`, and here-document bodies are consumed from the line after the
operator. Refused (`{"read": False}`): `(`, `)`, `;;`, `$(`, a backtick, `<(`, `>(`, `$'`, an unterminated
quote or here-document, a redirection without a target, a here-document body that substitutes, an
expanded program word, and the programs `if then else elif fi for while until do done case esac select
function eval source . { } [[ ]]`.

What it recognises as a write is a short table and the redirections: `tee`, `touch`, `mkdir`, `rm`,
`rmdir` (every file operand), `cp`, `mv`, `ln`, `install` (the last operand), and `sed -i`. No other
program adds a write, whatever its arguments, and a wrapper (`sudo`, `env`, `xargs`) is the program, not
unwrapped: an empty `writes` is never a claim that nothing is written. A path inside a word is found
(`of=/etc/passwd`, `-o/etc/x`, `host:/etc/`, `DESTDIR=/etc`), and a path that cannot be placed (an
expansion, `~`, a brace expansion, a relative path after an unknown `cd`) counts as outside, never as
inside the root. `/dev/null` and its kin are neither writes nor outside.

Pure and total: no I/O, no environment, no clock; equal inputs give equal outputs; it never raises for
any `str`.
"""
import posixpath
import re

LONG_CHARS = 200
LONG_LINES = 3

_RESERVED = frozenset("if then else elif fi for while until do done case esac select function eval "
                      "source . { } [[ ]]".split())
_DEVICES = frozenset(f"/dev/{name}" for name in "null stdin stdout stderr tty zero random urandom".split())
_ASSIGNMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=")
_WORD_ASSIGNMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_.-]*=")
_NAME_SPLIT = re.compile(r"[\s'\"`()\[\]{},;=<>|&]+")
_COPY_TARGET = re.compile(r"[0-9]+-?|-")
_CLUSTER = re.compile(r"-[A-Za-z]+")
_CLUSTER_SIGNED = re.compile(r"[-+][A-Za-z]+")
_COMMA_COLON = re.compile(r"[,:]")
_GLUE = re.compile(r"[^A-Za-z0-9_.+-]")
_EXTENSION = re.compile(r"[A-Za-z0-9]{1,8}")
_SHELLS = frozenset({"sh", "bash", "zsh", "dash", "ksh"})
_CODE_FLAG = {"sh": "c", "bash": "c", "zsh": "c", "dash": "c", "ksh": "c", "python": "c", "python3": "c",
              "node": "e", "perl": "e", "ruby": "e"}
_PYTHON_VERSION = re.compile(r"python3\.[0-9]+")
_SHELL_VALUES = frozenset({"-o", "+o", "-O", "+O", "--rcfile", "--init-file"})
_VALUE_OPTIONS = {"python": frozenset({"-W", "-X", "-Q", "--check-hash-based-pycs"}),
                  "node": frozenset({"-r", "--require", "--import", "--loader", "--experimental-loader"}),
                  "perl": frozenset({"-I"}), "ruby": frozenset({"-r", "-I"})}
_STDIN_OPERANDS = frozenset({"-", "/dev/stdin", "/dev/fd/0"})
_SSH_VALUES = frozenset("BbcDEeFIiJLlmOopQRSWw")
_REMOVERS = frozenset({"tee", "touch", "mkdir", "rm", "rmdir"})
_COPIERS = frozenset({"cp", "mv", "ln", "install"})
_WRITING_REDIRECTS = frozenset({">", ">>", ">|", "&>", "&>>", "<>"})
_WORD_END = " \t\n;&|()<>"
_BLANKS = " \t"


class _Refuse(ValueError):
    """The text is outside the grammar."""


class _Word:
    """A scanned word: its value with quotes removed, and what the quoting hid."""

    __slots__ = ("value", "expanded", "quoted", "unquoted")

    def __init__(self, value, expanded, quoted, unquoted):
        self.value = value
        self.expanded = expanded
        self.quoted = quoted
        self.unquoted = unquoted

    @property
    def tilde(self):
        return self.unquoted[:1] == "~"

    @property
    def brace(self):
        text = self.unquoted
        start = text.find("{")
        if start < 0:
            return False
        marks = [at for at in (text.find(",", start), text.find("..", start)) if at >= 0]
        return bool(marks) and text.find("}", min(marks)) >= 0

    @property
    def text(self):
        return any(char in self.value for char in " \t\n")

    @property
    def option(self):
        return self.value.startswith("-") and len(self.value) > 1


class _Item:
    """One word, redirection or here-document of a simple command, in text order."""

    __slots__ = ("kind", "word", "op", "role", "written", "body", "strip")

    def __init__(self, kind, word, op=""):
        self.kind = kind
        self.word = word
        self.op = op
        self.role = "arg"
        self.written = False
        self.body = None
        self.strip = False


def is_long(command):
    return len(command) > LONG_CHARS or command.count("\n") + 1 > LONG_LINES


def summarize(command, root):
    """The wire summary of a long command, None for a short one, `{"read": False}` for unreadable text."""
    if not is_long(command):
        return None
    try:
        return _Reader(root).read(*_scan(command))
    except (ValueError, IndexError, RecursionError):
        return {"read": False}


def _scan(text):
    """Split the text into simple commands (lists of items), refusing what the grammar does not read."""
    size = len(text)
    commands = []
    piped = []
    items = []
    pending = []
    pipe_next = False

    def blanks(at):
        while at < size:
            if text[at] in _BLANKS:
                at += 1
            elif text.startswith("\\\n", at):
                at += 2
            else:
                break
        return at

    def word_at(at):
        value, unquoted = [], []
        expanded = quoted = False
        while at < size:
            char = text[at]
            if char in _WORD_END:
                break
            if char == "\\":
                if at + 1 >= size:
                    value.append("\\")
                    unquoted.append("\0")
                    at += 1
                elif text[at + 1] == "\n":
                    at += 2
                else:
                    value.append(text[at + 1])
                    unquoted.append("\0")
                    quoted = True
                    at += 2
            elif char == "'":
                end = text.find("'", at + 1)
                if end < 0:
                    raise _Refuse("unterminated quote")
                value.append(text[at + 1:end])
                unquoted.append("\0" * (end - at - 1))
                quoted = True
                at = end + 1
            elif char == '"':
                at += 1
                while True:
                    if at >= size:
                        raise _Refuse("unterminated quote")
                    inner = text[at]
                    if inner == '"':
                        at += 1
                        break
                    if inner == "`" or text.startswith("$(", at):
                        raise _Refuse("substitution")
                    if inner == "\\":
                        following = text[at + 1:at + 2]
                        if following == "\n":
                            at += 2
                            continue
                        if following and following in '"\\$`':
                            value.append(following)
                            unquoted.append("\0")
                            at += 2
                            continue
                    if inner == "$":
                        expanded = True
                    value.append(inner)
                    unquoted.append("\0")
                    at += 1
                quoted = True
            elif char == "`" or text.startswith("$(", at) or text.startswith("$'", at):
                raise _Refuse("substitution")
            else:
                expanded = expanded or char == "$"
                value.append(char)
                unquoted.append(char)
                at += 1
        return _Word("".join(value), expanded, quoted, "".join(unquoted)), at

    def operator_at(at):
        if text.startswith(("<(", ">("), at):
            raise _Refuse("process substitution")
        for operator in ("&>>", "&>", "<<<", "<<-", "<<", "<>", "<&", ">>", ">|", ">&", ">", "<"):
            if text.startswith(operator, at):
                return operator, at + len(operator)
        raise _Refuse("operator")

    def redirect(at):
        operator, at = operator_at(at)
        at = blanks(at)
        if at >= size or text[at] in "\n;&|<>()":
            raise _Refuse("redirection without a target")
        target, at = word_at(at)
        if operator in ("<<", "<<-"):
            item = _Item("heredoc", target, operator)
            item.strip = operator == "<<-"
            pending.append(item)
        else:
            item = _Item("redir", target, operator)
        items.append(item)
        return at

    def end_command():
        nonlocal items, pipe_next
        if items:
            commands.append(items)
            piped.append(pipe_next)
            pipe_next = False
            items = []

    def read_bodies(at):
        for item in pending:
            delimiter = item.word.value.lstrip("\t") if item.strip else item.word.value
            body = []
            while True:
                if at >= size:
                    raise _Refuse("here-document without its delimiter")
                end = text.find("\n", at)
                line = text[at:] if end < 0 else text[at:end]
                at = size if end < 0 else end + 1
                if (line.lstrip("\t") if item.strip else line) == delimiter:
                    break
                body.append(line.lstrip("\t") if item.strip else line)
            if not item.word.quoted and any("$(" in line or "`" in line for line in body):
                raise _Refuse("a here-document body that substitutes")
            item.body = body
        pending.clear()
        return at

    at = 0
    while at < size:
        char = text[at]
        if char in _BLANKS or text.startswith("\\\n", at):
            at = blanks(at)
        elif char == "\n":
            end_command()
            at = read_bodies(at + 1) if pending else at + 1
        elif char == "#":
            end = text.find("\n", at)
            at = size if end < 0 else end
        elif char in "()" or text.startswith(";;", at):
            raise _Refuse("grouping")
        elif char == ";":
            end_command()
            at += 1
        elif char in "&|" and not text.startswith("&>", at):
            end_command()
            follow = text[at + 1:at + 2]
            pipe_next = char == "|" and follow != "|"
            at += 2 if follow in (("&", "|") if char == "|" else ("&",)) else 1
        elif char in "<>&":
            at = redirect(at)
        else:
            word, at = word_at(at)
            if at < size and text[at] in "<>" and word.value.isdigit() and not word.quoted:
                at = redirect(at)
            else:
                items.append(_Item("word", word))
    if pending:
        raise _Refuse("here-document without its delimiter")
    end_command()
    return commands, piped


def _named_paths(text):
    """The path-looking tokens a script's text names (rule 12)."""
    found = []
    for token in _NAME_SPLIT.split(text):
        if not token or "://" in token or not token.strip("/."):
            continue
        if token.startswith(("/", "~/", "./", "../")):
            found.append(token)
        elif "/" in token:
            last = token.rsplit("/", 1)[1]
            if "." in last and _EXTENSION.fullmatch(last.rsplit(".", 1)[1]):
                found.append(token)
    return found


def _path_like(part):
    return bool(part) and (part.startswith(("/", "~", "./", "../")) or part in (".", "..") or "/" in part)


def _glued_path(part):
    """True when a path hides behind a prefix (`@/etc/x`): joining it under the base would hide it."""
    head = part.split("/", 1)[0]
    return bool(head) and "/" in part and not part.startswith(("~", ".")) and bool(_GLUE.search(head))


def _program_kind(program):
    name = posixpath.basename(program)
    if name in _SHELLS or name in ("python", "python3", "node", "perl", "ruby") or _PYTHON_VERSION.fullmatch(name):
        return "interpreter", _CODE_FLAG.get(name, "c")
    return name, ""


class _Reader:
    """Folds scanned commands into the wire summary, tracking the working directory a `cd` sets."""

    def __init__(self, root):
        self.root = posixpath.normpath(root) if isinstance(root, str) and root.startswith("/") else None
        self.base = self.root
        self.runs, self.writes, self.outside = {}, {}, {}
        self.scripts = []

    def read(self, commands, piped):
        chain = []
        for items, fed in zip(commands, piped):
            chain = chain if fed else []
            chain.append((items, self.command(items, list(chain))))
        return {"read": True, "runs": list(self.runs), "writes": list(self.writes),
                "outside": list(self.outside), "scripts": self.scripts}

    def inside(self, path):
        if self.root is None:
            return False
        return path == self.root or path.startswith(self.root if self.root.endswith("/") else self.root + "/")

    def place(self, candidate, unplaceable):
        """The normalized absolute path of a candidate, or None when the text cannot place it."""
        if unplaceable or "$" in candidate or candidate.startswith("~"):
            return None
        if candidate.startswith("/"):
            return posixpath.normpath(candidate)
        if self.base is None:
            return None
        return posixpath.normpath(posixpath.join(self.base, candidate))

    def touch(self, candidate, unplaceable=False):
        """Record a touched candidate; return its placed path (None when unplaceable or a device)."""
        if not candidate:
            return None
        placed = self.place(candidate, unplaceable)
        if placed in _DEVICES:
            return None
        if placed is None:
            self.outside[candidate] = True
        elif not self.inside(placed):
            self.outside[placed] = True
        return placed

    def write(self, text):
        if posixpath.normpath(text) not in _DEVICES and text:
            self.writes[text] = True

    def operand(self, word, written):
        """A file operand or redirection target: the whole word is one candidate."""
        if written:
            self.write(word.value)
        if "://" in word.value:
            return None
        return self.touch(word.value, word.expanded or word.brace)

    def argument(self, word):
        """The candidates of an ordinary argument word (rule 8)."""
        value = word.value
        if "://" in value:
            return
        if word.brace:
            self.touch(value, True)
        elif word.text:
            for path in _named_paths(value):
                self.touch(path, word.expanded)
        else:
            if value.startswith("-"):
                if len(value) > 2 and value[1] != "-" and "/" in value.split("=", 1)[0]:
                    value = value[2:]
                elif "=" in value:
                    value = value.split("=", 1)[1]
                else:
                    return
            elif _WORD_ASSIGNMENT.match(value):
                value = value.split("=", 1)[1]
            for part in _COMMA_COLON.split(value):
                if _path_like(part):
                    self.touch(part, word.expanded or _glued_path(part))

    def script(self, program, text, lines):
        paths = list(dict.fromkeys(_named_paths(text)))
        for path in paths:
            self.touch(path)
        self.scripts.append({"program": program, "lines": lines, "paths": paths})

    @staticmethod
    def remote_of(arguments):
        """(name, the arguments after it) for what `ssh`'s standard input reaches: its remote login shell
        when it has no command, else the interpreter the remote command names (one word or the tokens of a
        quoted one); (None, []) when the remote command is no interpreter. Options are read again after the
        host, as OpenSSH does."""
        host = None
        command = []
        ended = False
        at = 0
        while at < len(arguments):
            item = arguments[at]
            value = item.word.value
            if not ended and value == "--":
                ended = True
            elif not ended and value.startswith("-") and len(value) > 1:
                letters = [char for char in value[1:] if char in _SSH_VALUES]
                if letters and value[1:].index(letters[0]) == len(value) - 2:
                    at += 1
            elif host is None:
                host = item
            else:
                command = arguments[at:]
                break
            at += 1
        if not command:
            return "ssh", []
        tokens = [token for item in command
                  for token in (item.word.value.split() if item.word.text else [item.word.value])]
        for at, token in enumerate(tokens):
            if _program_kind(token)[0] == "interpreter":
                return token, [_Item("word", _Word(rest, False, False, rest)) for rest in tokens[at + 1:]]
        return None, []

    @staticmethod
    def interpreter_of(program, arguments):
        """(name, the arguments after it) for the interpreter a command reaches, directly, behind a wrapper
        or through `ssh`."""
        if program is not None and _program_kind(program.value)[0] == "interpreter":
            return program.value, arguments
        if program is not None and posixpath.basename(program.value) == "ssh":
            return _Reader.remote_of(arguments)
        for at, item in enumerate(arguments):
            if _program_kind(item.word.value)[0] == "interpreter":
                return item.word.value, arguments[at + 1:]
            if posixpath.basename(item.word.value) == "ssh":
                return _Reader.remote_of(arguments[at + 1:])
        return None, []

    def reads_stdin(self, name, rest):
        """True when the interpreter takes its code from standard input: no code argument, and no script
        operand once the values of its value-taking options are skipped (`-`, `/dev/stdin` are stdin)."""
        flag = _program_kind(name)[1]
        if any(item.word.option and self.code_flag(name, flag, item.word.value) for item in rest):
            return False
        if any(item.word.value == "-s" for item in rest):
            return True
        base = posixpath.basename(name)
        family = "python" if base.startswith("python") else base
        takes = _SHELL_VALUES if base in _SHELLS else _VALUE_OPTIONS.get(family, frozenset())
        letters = frozenset(option[1] for option in takes if len(option) == 2)
        operands = []
        skip = ended = False
        for item in rest:
            value = item.word.value
            if skip:
                skip = False
            elif ended:
                operands.append(value)
            elif value in takes or (_CLUSTER_SIGNED.fullmatch(value) and value[-1] in letters):
                skip = True
            elif value == "--":
                ended = True
            elif not item.word.option:
                operands.append(value)
        return all(value in _STDIN_OPERANDS for value in operands)

    @staticmethod
    def stdin_texts(items):
        """The here-document and here-string texts of a command: (text, line count)."""
        texts = []
        for item in items:
            if item.kind == "heredoc":
                texts.append(("\n".join(item.body), len(item.body)))
            elif item.kind == "redir" and item.op == "<<<":
                texts.append((item.word.value, item.word.value.count("\n") + 1))
        return texts

    def command(self, items, feeders=()):
        """Fold one simple command; return whether it reaches an interpreter. `feeders` are the earlier
        (items, reaches) commands of its pipeline."""
        words = [item for item in items if item.kind == "word"]
        first = 0
        while first < len(words) and (words[first].word.value == "!"
                                      or _ASSIGNMENT.match(words[first].word.value)):
            words[first].role = "skip" if words[first].word.value == "!" else "arg"
            first += 1
        program = words[first].word if first < len(words) else None
        arguments = words[first + 1:]
        self.placed = None
        self.interpreter, rest = self.interpreter_of(program, arguments)
        if (feeders and self.interpreter is not None and not self.stdin_texts(items)
                and self.reads_stdin(self.interpreter, rest)):
            fed = [text for before, reaches in feeders if not reaches for text in self.stdin_texts(before)]
            if not fed:
                raise _Refuse("an interpreter fed code the console cannot read")
            for text, lines in fed:
                self.script(self.interpreter, text, lines)
        if program is not None:
            if program.expanded or program.value in _RESERVED:
                raise _Refuse("a program the console cannot read")
            self.runs[program.value] = True
            words[first].role = "program"
            self.classify(program.value, arguments)
        for item in items:
            self.emit(item, program)
        if program is not None and program.value == "cd":
            self.base = self.placed
        return self.interpreter is not None

    def classify(self, program, arguments):
        """Assign each argument its role for this program."""
        kind, flag = _program_kind(program)
        if program == "cd":
            kind = "cd"
        options, operands = [], []
        done = False
        for item in arguments:
            if not done and item.word.option:
                options.append(item)
                done = item.word.value == "--"
            else:
                operands.append(item)
        if kind in _REMOVERS:
            for item in operands:
                item.role, item.written = "file", True
        elif kind in _COPIERS:
            for item in operands:
                item.role = "file"
            if len(operands) >= 2:
                operands[-1].written = True
        elif kind == "sed":
            self.classify_sed(arguments)
        elif kind == "cd":
            if operands:
                operands[0].role = "cd"
        elif kind == "interpreter":
            for at, item in enumerate(arguments):
                value = item.word.value
                if item.word.option and self.code_flag(program, flag, value) and at + 1 < len(arguments):
                    arguments[at + 1].role = "code"
                    break

    @staticmethod
    def code_flag(program, flag, value):
        if value == f"-{flag}" or (_CLUSTER.fullmatch(value) and flag in value[1:]):
            return True
        return posixpath.basename(program) == "node" and value == "--eval"

    @staticmethod
    def classify_sed(arguments):
        in_place = scripted = False
        operands = []
        done = False
        at = 0
        while at < len(arguments):
            item = arguments[at]
            value = item.word.value
            if not done and item.word.option:
                done = value == "--"
                if value.startswith("-i") or value.startswith("--in-place"):
                    in_place = True
                if value in ("-e", "--expression", "-f", "--file"):
                    scripted = True
                    if at + 1 < len(arguments):
                        arguments[at + 1].role = "skip" if value in ("-e", "--expression") else "file"
                        at += 1
                elif value.startswith(("-e", "-f", "--expression=", "--file=")):
                    scripted = True
            elif item.role == "arg":
                operands.append(item)
            at += 1
        if not scripted and operands:
            operands[0].role = "skip"
            operands = operands[1:]
        for item in operands:
            item.role, item.written = "file", in_place

    def emit(self, item, program):
        word = item.word
        if item.kind == "word":
            if item.role == "program" or item.role == "skip":
                return
            if item.role == "file":
                self.operand(word, item.written)
            elif item.role == "cd":
                self.placed = None if word.value == "-" else self.operand(word, False)
            elif item.role == "code":
                self.script(program.value, word.value, word.value.count("\n") + 1)
            else:
                self.argument(word)
        elif item.kind == "heredoc":
            if self.interpreter is not None:
                self.script(self.interpreter, "\n".join(item.body), len(item.body))
        elif item.op == "<<<":
            if self.interpreter is not None:
                self.script(self.interpreter, word.value, word.value.count("\n") + 1)
        else:
            value = word.value
            if item.op in (">&", "<&") and _COPY_TARGET.fullmatch(value):
                return
            self.operand(word, item.op in _WRITING_REDIRECTS or item.op == ">&")
