"""Verify local module/asset cache versions, or atomically bump existing versions."""
from __future__ import annotations

import argparse
import os
import re
import tempfile
from collections import Counter, defaultdict
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src/rag_tech_retriever/api/static/shilie"
VERSION = Path(__file__).with_name("static-version.txt")


class HtmlAssets(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.urls: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "script" and values.get("src"):
            self.urls.append(values["src"] or "")
        if tag == "link" and values.get("rel") in {"stylesheet", "icon"} and values.get("href"):
            self.urls.append(values["href"] or "")


def skip_quoted(text: str, start: int) -> int:
    quote = text[start]
    i = start + 1
    while i < len(text):
        if text[i] == "\\":
            i += 2
        elif text[i] == quote:
            return i + 1
        else:
            i += 1
    return i


def skip_template(text: str, start: int) -> tuple[int, list[str]]:
    """Skip a template, recursively extracting its JavaScript expressions."""
    i, expressions = start + 1, []
    while i < len(text):
        if text[i] == "\\":
            i += 2
        elif text[i] == "`":
            return i + 1, expressions
        elif text.startswith("${", i):
            begin = i + 2
            i, depth = begin, 1
            while i < len(text) and depth:
                if text[i] in "\"'":
                    i = skip_quoted(text, i)
                elif text[i] == "`":
                    i, nested = skip_template(text, i)
                    expressions.extend(nested)
                elif text.startswith("//", i):
                    end = text.find("\n", i)
                    i = len(text) if end < 0 else end
                elif text.startswith("/*", i):
                    end = text.find("*/", i + 2)
                    i = len(text) if end < 0 else end + 2
                elif text[i] == "{":
                    depth += 1
                    i += 1
                elif text[i] == "}":
                    depth -= 1
                    i += 1
                else:
                    i += 1
            expressions.append(text[begin:i - 1])
        else:
            i += 1
    return i, expressions


def js_tokens(text: str) -> list[tuple[str, str]]:
    """Tokenize import-relevant syntax without treating comments or strings as code."""
    tokens: list[tuple[str, str]] = []
    i = 0
    while i < len(text):
        c = text[i]
        if c.isspace():
            i += 1
            continue
        if text.startswith("//", i):
            end = text.find("\n", i)
            i = len(text) if end < 0 else end
            continue
        if text.startswith("/*", i):
            end = text.find("*/", i + 2)
            i = len(text) if end < 0 else end + 2
            continue
        if c == "/" and (not tokens or tokens[-1][1] in {"=", ">", "(", "[", "{", ",", ":", "return", "case"}):
            start, i, inside_class = i, i + 1, False
            while i < len(text):
                if text[i] == "\\":
                    i += 2
                elif text[i] == "[":
                    inside_class = True
                    i += 1
                elif text[i] == "]":
                    inside_class = False
                    i += 1
                elif text[i] == "/" and not inside_class:
                    i += 1
                    while i < len(text) and text[i].isalpha():
                        i += 1
                    break
                else:
                    i += 1
            tokens.append(("regex", text[start:i]))
            continue
        if c == "`":
            i, expressions = skip_template(text, i)
            for expression in expressions:
                tokens.append(("punct", "("))
                tokens.extend(js_tokens(expression))
                tokens.append(("punct", ")"))
            continue
        if c in "\"'":
            end = skip_quoted(text, i)
            tokens.append(("string", text[i + 1:end - 1]))
            i = end
            continue
        if c.isalpha() or c in "_$":
            start = i
            i += 1
            while i < len(text) and (text[i].isalnum() or text[i] in "_$"):
                i += 1
            tokens.append(("word", text[start:i]))
            continue
        tokens.append(("punct", c))
        i += 1
    return tokens


def js_imports(text: str) -> tuple[list[str], bool]:
    tokens = js_tokens(text)
    refs: list[str] = []
    nonliteral = False
    for i, (kind, value) in enumerate(tokens):
        if kind != "word" or value not in {"import", "export"} or i + 1 >= len(tokens):
            continue
        next_kind, next_value = tokens[i + 1]
        if value == "import" and next_value == "(":
            if i + 3 < len(tokens) and tokens[i + 2][0] == "string" and tokens[i + 3][1] == ")":
                refs.append(tokens[i + 2][1])
            else:
                nonliteral = True
        elif value == "import" and next_kind == "string":
            refs.append(next_value)
        elif next_value in {"{", "*"} or (value == "import" and next_kind == "word"):
            for j in range(i + 1, min(len(tokens), i + 100)):
                if tokens[j][1] == ";":
                    break
                if tokens[j][1] == "from" and j + 1 < len(tokens) and tokens[j + 1][0] == "string":
                    refs.append(tokens[j + 1][1])
                    break
    return refs, nonliteral


def local_refs() -> list[tuple[str, str]]:
    parser = HtmlAssets()
    parser.feed((STATIC / "index.html").read_text(encoding="utf-8"))
    refs = [("index.html", url) for url in parser.urls]
    for path in sorted(STATIC.glob("*.js")):
        urls, _ = js_imports(path.read_text(encoding="utf-8"))
        refs.extend((path.name, url) for url in urls)
    return refs


def check(expected: str) -> list[str]:
    refs = local_refs()
    problems = []
    if not refs:
        return ["no local static references found"]
    for name, url in refs:
        parsed = urlsplit(url)
        if parsed.scheme or parsed.netloc or not url.startswith(("./", "../", "/static/")):
            problems.append(f"{name}: external or unsupported runtime reference: {url}")
            continue
        value = parse_qs(parsed.query).get("v", [])
        if value != [expected]:
            problems.append(f"{name}: {url}: expected v={expected}")
    for path in sorted(STATIC.glob("*.js")):
        _, nonliteral = js_imports(path.read_text(encoding="utf-8"))
        if nonliteral:
            problems.append(f"{path.name}: non-literal dynamic import cannot be version-verified")
    for path in sorted(STATIC.glob("*.css")):
        if re.search(r"@import\b", path.read_text(encoding="utf-8"), re.IGNORECASE):
            problems.append(f"{path.name}: CSS @import is not allowed")
    return problems


def atomic_write(path: Path, data: bytes) -> None:
    fd, name = tempfile.mkstemp(prefix=".static-version-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--set", metavar="N", help="bump all existing version references")
    args = parser.parse_args()
    current = VERSION.read_text(encoding="ascii").strip()
    if not current.isdecimal():
        print("FAIL invalid version file")
        return 1
    problems = check(current)
    if problems:
        print("FAIL static version checks:")
        for problem in problems:
            print(problem)
        return 1
    if args.set:
        if not args.set.isdecimal() or int(args.set) <= int(current):
            print("FAIL new version must be a larger integer")
            return 1
        files = [STATIC / "index.html", *sorted(STATIC.glob("*.js")), VERSION]
        original = {p: p.read_bytes() for p in files}
        grouped: dict[str, Counter[str]] = defaultdict(Counter)
        for name, url in local_refs():
            grouped[name][url] += 1
        updates = dict(original)
        for p in files[:-1]:
            data = original[p]
            for url, expected_count in grouped[p.name].items():
                before = url.encode("utf-8")
                after = re.sub(r"(?<=[?&])v=\d+(?=&|$)", f"v={args.set}", url).encode("utf-8")
                single, double = b"'" + before + b"'", b'"' + before + b'"'
                if data.count(single) + data.count(double) != expected_count:
                    print(f"FAIL ambiguous asset literal in {p.name}: {url}")
                    return 1
                data = data.replace(single, b"'" + after + b"'").replace(double, b'"' + after + b'"')
            updates[p] = data
        updates[VERSION] = (args.set + "\n").encode("ascii")
        try:
            for p in files:
                if updates[p] != original[p]:
                    atomic_write(p, updates[p])
            if check(args.set):
                raise ValueError("version verification failed")
        except Exception:
            for p, data in original.items():
                if p.read_bytes() != data:
                    atomic_write(p, data)
            raise
        current = args.set
    print(f"OK {len(local_refs())} local asset/module references at v{current}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
