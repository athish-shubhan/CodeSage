"""Checks the agent's final answer against what its tools actually returned.

A citation `[path:start-end]` is grounded if, during this run, a tool put
that file region in front of the model: a search_code hit whose line range
overlaps it, an expand_context window that covers it, or a get_file read of
that file. Anything else was invented or misremembered by the model. Lines
removed from a tool result as instruction-like text (untrusted.py) do not
count: the model never saw them as content, so they cannot ground anything.

A grounded range is not proof the answer describes it correctly, so a second
check looks at what the answer says next to each citation: code identifiers
(backticked names, call-shaped or snake_case names, `class X`/`def x`, file
paths) in the same sentence must appear in the text the tools returned for
the cited range. Ones that do not are reported as unsupported identifiers.

Both are regex, interval, and substring checks, not an LLM judge, so they
are cheap enough to run on every response and their result is not a matter
of opinion.
"""
from __future__ import annotations

import keyword
import re

from app.agent.state import InjectionFlag, ToolCallRecord

CITATION_RE = re.compile(r"\[([\w./-]+\.\w+):(\d+)(?:-(\d+))?\]")
WHOLE_FILE = (1, 10**9)
# Identifier text is looked up this many lines either side of the cited
# range, so a citation that is off by a line or two is not punished twice,
# plus the def/class lines that enclose the range.
SLACK_LINES = 2

_DEF_LINE_RE = re.compile(r"^(\s*)(?:async\s+)?(?:def|class|function|func|fn)\s")
_HEADER_LINE_RE = re.compile(r"^\[([\w./-]+\.\w+):(\d+)(?:-(\d+))?\][ \t]*$", re.MULTILINE)


def extract(text: str) -> list[tuple[str, int, int]]:
    return [(p, int(s), int(e) if e else int(s)) for p, s, e in CITATION_RE.findall(text)]


def removed_lines(flags: list[InjectionFlag]) -> dict[str, set[int]]:
    """{path: {line, ...}} of file lines that untrusted.py removed."""
    out: dict[str, set[int]] = {}
    for f in flags:
        if f.source_path and f.start_line is not None:
            out.setdefault(f.source_path, set()).update(range(f.start_line, (f.end_line or f.start_line) + 1))
    return out


def _evidence(tool_calls: list[ToolCallRecord]) -> dict[str, list[tuple[int, int]]]:
    spans: dict[str, list[tuple[int, int]]] = {}
    for tc in tool_calls:
        if tc.name == "search_code":
            for path, start, end in extract(tc.result):
                spans.setdefault(path, []).append((start, end))
        elif tc.name == "expand_context" and not tc.result.startswith("Could not expand"):
            extra = tc.args.get("extra_lines", 20)
            start = max(1, tc.args.get("start_line", 1) - extra)
            spans.setdefault(tc.args.get("source_path", ""), []).append((start, tc.args.get("end_line", 0) + extra))
        elif tc.name == "get_file" and not tc.result.startswith("File not found"):
            spans.setdefault(tc.args.get("source_path", ""), []).append(WHOLE_FILE)
    return spans


def _has_live_line(lo: int, hi: int, gone: set[int]) -> bool:
    # Stops at the first line not removed, so this runs at most len(gone)+1
    # times however large the range is.
    for line in range(lo, hi + 1):
        if line not in gone:
            return True
    return False


def check(answer: str, tool_calls: list[ToolCallRecord], removed: dict[str, set[int]] | None = None) -> dict:
    """Returns {"grounded": [...], "ungrounded": [...]} as "path:start-end" strings.
    `removed` ({path: lines}, see removed_lines) are lines that do not count
    as evidence; a citation is grounded only if it overlaps a line a tool
    returned and that was not removed."""
    evidence = _evidence(tool_calls)
    removed = removed or {}
    grounded, ungrounded = [], []
    for path, start, end in extract(answer):
        gone = removed.get(path, set())
        ok = any(
            _has_live_line(max(s, start), min(e, end), gone) for s, e in evidence.get(path, []) if s <= end and start <= e
        )
        (grounded if ok else ungrounded).append(f"{path}:{start}-{end}")
    return {"grounded": grounded, "ungrounded": ungrounded}


# --- identifier support -------------------------------------------------

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|\n+")
_BACKTICK_RE = re.compile(r"`([^`\n]+)`")
_URL_RE = re.compile(r"https?://\S+")
_EXT = r"(?:py|pyi|js|jsx|ts|tsx|go|rs|java|kt|rb|c|h|cc|cpp|hpp|cs|md|yml|yaml|json|toml|proto|sh|txt|cfg|ini|sql)"
_PATH_RE = re.compile(rf"(?<![\w/.-])((?:[\w.-]+/)*[\w-]+\.{_EXT})(?![\w/])")
_PROSE_PATTERNS = [
    re.compile(r"(?<![\w.])([A-Za-z_][\w.]*\w)\(\)"),  # name()
    re.compile(r"(?<![\w.])(_*[A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)+)(?![\w(])"),  # snake_case, SCREAMING_SNAKE
    re.compile(r"(?<![\w.])(_+[A-Za-z][A-Za-z0-9]*)(?![\w(])"),  # _private
    re.compile(r"\bclass\s+([A-Z]\w*[A-Z]\w*)"),  # class AgentState
    re.compile(r"\b([A-Z][a-z0-9]+(?:[A-Z][a-z0-9]+)+)\s+class\b"),  # the AgentState class
    re.compile(r"\bdef\s+([a-z_]\w*)"),
]
_SKIP = set(keyword.kwlist) | {"self", "cls"}


def _is_path(token: str) -> bool:
    m = _PATH_RE.fullmatch(token)
    if not m:
        return False
    stem = token.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    # "auth.py", "README.md", "app/x.ts" -- but not prose like "Node.js".
    return "/" in token or stem == stem.lower() or stem == stem.upper()


def _identifiers(prose: str) -> list[str]:
    """Identifiers a sentence names, in first-seen order. Backticked spans
    count when they are a name, a call, a `def`/`class` line, a path, or a
    quoted string; other backticked expressions are skipped rather than guessed at."""
    found: list[str] = []
    for content in _BACKTICK_RE.findall(prose):
        content = content.strip()
        if len(content) >= 2 and content[0] == content[-1] and content[0] in "\"'":
            found.append(content)  # string literal, checked verbatim
        elif _is_path(content):
            found.append(content)
        elif m := re.fullmatch(r"(?:async\s+)?(?:def|class)\s+([A-Za-z_]\w*).*", content):
            found.append(m.group(1))
        elif m := re.fullmatch(r"([A-Za-z_][\w.]*?)(?:\(.*\))?", content):
            found.append(m.group(1))
    rest = _URL_RE.sub(" ", _BACKTICK_RE.sub(" ", prose))
    found += [m.group(1) for m in _PATH_RE.finditer(rest) if _is_path(m.group(1))]
    rest = _PATH_RE.sub(" ", rest)
    for pattern in _PROSE_PATTERNS:
        found += pattern.findall(rest)
    out: list[str] = []
    for ident in found:
        if ident not in out and ident not in _SKIP and len(ident) >= 2 and not ident.isdigit():
            out.append(ident)
    return out


def attributed_identifiers(answer: str) -> list[tuple[str, list[tuple[str, int, int]]]]:
    """[(identifier, [citations in the same sentence])] for every sentence
    that has a citation. A sentence that is only citations ("... text. [a.py:1-3]")
    is attached to the sentence before it."""
    sentences: list[tuple[str, list[tuple[str, int, int]]]] = []
    for raw in _SENTENCE_SPLIT_RE.split(answer):
        cites = extract(raw)
        prose = CITATION_RE.sub(" ", raw)
        if cites and sentences and not re.search(r"\w", prose):
            sentences[-1][1].extend(cites)
        else:
            sentences.append((prose, cites))
    return [(ident, cites) for prose, cites in sentences if cites for ident in _identifiers(prose)]


def _segments(tool_calls: list[ToolCallRecord]) -> dict[str, list[tuple[int, list[str]]]]:
    """{path: [(first_line, lines), ...]}: the text each tool returned, placed at its file line numbers."""
    segs: dict[str, list[tuple[int, list[str]]]] = {}
    for tc in tool_calls:
        if tc.name == "search_code":
            headers = list(_HEADER_LINE_RE.finditer(tc.result))
            for k, m in enumerate(headers):
                body_end = headers[k + 1].start() if k + 1 < len(headers) else len(tc.result)
                body = tc.result[m.end() : body_end]
                body = body[1:] if body.startswith("\n") else body
                segs.setdefault(m.group(1), []).append((int(m.group(2)), body.split("\n")))
        elif tc.name == "expand_context" and not tc.result.startswith("Could not expand"):
            start = max(1, tc.args.get("start_line", 1) - tc.args.get("extra_lines", 20))
            segs.setdefault(tc.args.get("source_path", ""), []).append((start, tc.result.split("\n")))
        elif tc.name == "get_file" and not tc.result.startswith("File not found"):
            segs.setdefault(tc.args.get("source_path", ""), []).append((1, tc.result.split("\n")))
    return segs


def _enclosing_headers(lines: list[str], idx: int) -> list[str]:
    """The def/class lines that enclose lines[idx], innermost first, so
    "`refund_payment` skips approval [payments.py:9-10]" can be backed by the
    `def refund_payment` line above the cited body."""
    target = next((ln for ln in lines[idx:] if ln.strip()), "")
    indent = len(target) - len(target.lstrip())
    headers = []
    for line in reversed(lines[:idx]):
        if indent == 0:
            break
        m = _DEF_LINE_RE.match(line)
        if m and len(m.group(1)) < indent:
            headers.append(line)
            indent = len(m.group(1))
    return headers


def _cited_text(segs: dict[str, list[tuple[int, list[str]]]], path: str, start: int, end: int) -> str:
    parts = []
    for first, lines in segs.get(path, []):
        lo, hi = max(start - SLACK_LINES, first), min(end + SLACK_LINES, first + len(lines) - 1)
        if lo <= hi:
            parts += _enclosing_headers(lines, start - first) if start > first else []
            parts.append("\n".join(lines[lo - first : hi - first + 1]))
    return "\n".join(parts)


def _occurs(needle: str, haystack: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(needle)}(?!\w)", haystack) is not None


def _supported(ident: str, text: str, cited_paths: set[str]) -> bool:
    if ident[0] in "\"'":
        return ident[1:-1] in text
    if _is_path(ident):
        base = ident.rsplit("/", 1)[-1]
        if any(p == ident or p.endswith("/" + ident) or ident.endswith("/" + p) for p in cited_paths):
            return True
        return _occurs(ident, text) or _occurs(base, text) or _occurs(base.rsplit(".", 1)[0], text)
    # `rag_client.search` is backed by the full dotted name or by its last part.
    return _occurs(ident, text) or _occurs(ident.rsplit(".", 1)[-1], text)


def unsupported_identifiers(answer: str, tool_calls: list[ToolCallRecord]) -> list[dict]:
    """[{"identifier": ..., "citations": ["path:start-end", ...]}] for each
    identifier the answer attributes to its citations that none of the cited
    ranges' tool text contains. tool_calls must hold the text the model saw
    (after sanitizing), so a name that only appeared in removed text is unsupported."""
    segs = _segments(tool_calls)
    out = []
    for ident, cites in attributed_identifiers(answer):
        text = "\n".join(_cited_text(segs, p, s, e) for p, s, e in cites)
        if not _supported(ident, text, {p for p, _, _ in cites}):
            out.append({"identifier": ident, "citations": [f"{p}:{s}-{e}" for p, s, e in cites]})
    return out
