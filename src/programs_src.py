"""programs.py - reference programs for the rebuild arena. They run as black boxes in the sandbox; the
model sees only the usage docs and the outputs of inputs it chooses to probe (ProgramBench rules, scaled
down). Each program comes with ordered features and a seeded input generator per feature.

Any real executable (e.g. a ProgramBench task) plugs in the same way: RebuildTask(reference_files=...,
reference_argv=[...]) plus feature generators.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Callable


@dataclass
class Feature:
    name: str
    doc: str
    gen: Callable[[random.Random], str]


@dataclass
class Program:
    id: str
    docs: str
    source: str            # hidden reference implementation (Python, read stdin -> write stdout)
    features: list[Feature]


# ============================================================================ calc
CALC_SRC = r'''
import sys
class Err(Exception):
    pass
def tokenize(s):
    toks, i = [], 0
    while i < len(s):
        c = s[i]
        if c.isspace():
            i += 1; continue
        if c.isdigit():
            j = i
            while j < len(s) and s[j].isdigit():
                j += 1
            toks.append(int(s[i:j])); i = j; continue
        if c in "+-*/%^()":
            toks.append(c); i += 1; continue
        raise Err()
    return toks
class P:
    def __init__(s, t): s.t, s.i = t, 0
    def peek(s): return s.t[s.i] if s.i < len(s.t) else None
    def eat(s):
        v = s.peek(); s.i += 1; return v
    def expr(s):
        v = s.term()
        while s.peek() in ("+", "-"):
            op = s.eat(); r = s.term(); v = v + r if op == "+" else v - r
        return v
    def term(s):
        v = s.unary()
        while s.peek() in ("*", "/", "%"):
            op = s.eat(); r = s.unary()
            if op == "*":
                v = v * r; continue
            if r == 0:
                raise Err()
            q = abs(v) // abs(r)
            q = q if (v >= 0) == (r >= 0) else -q
            v = q if op == "/" else v - r * q
        return v
    def unary(s):
        if s.peek() == "-":
            s.eat(); return -s.unary()
        return s.power()
    def power(s):
        b = s.atom()
        if s.peek() == "^":
            s.eat(); e = s.unary()
            if e < 0 or e > 64:
                raise Err()
            return b ** e
        return b
    def atom(s):
        t = s.eat()
        if isinstance(t, int):
            return t
        if t == "(":
            v = s.expr()
            if s.eat() != ")":
                raise Err()
            return v
        raise Err()
out = []
for line in sys.stdin.read().split("\n"):
    if not line.strip():
        continue
    try:
        p = P(tokenize(line)); v = p.expr()
        if p.i != len(p.t):
            raise Err()
        out.append(str(v))
    except (Err, RecursionError):
        out.append("error")
sys.stdout.write("\n".join(out) + ("\n" if out else ""))
'''

CALC_DOCS = """calc - integer calculator.
Reads expressions from standard input, one per line, and prints one result line per expression.
Blank lines are ignored (they produce no output).
Numbers are non-negative decimal integer literals; spaces may appear anywhere between tokens.
Operators, from loosest to tightest binding:
  + -        addition, subtraction (left associative)
  * / %      multiplication, division, remainder (left associative). Division truncates toward zero
             and the remainder has the sign of the left operand (as in C).
  -x         unary minus (may repeat, e.g. --3)
  ^          power, right associative, binds tighter than unary minus (so -2^2 is -4); the exponent
             may itself start with unary minus.
Parentheses group as usual. Integers are unbounded.
Errors: for a malformed line, a division or remainder by zero, a negative exponent, or an exponent
greater than 64, print the single word: error"""


def _num(rng):
    return str(rng.choice([rng.randint(0, 9), rng.randint(0, 99), rng.randint(0, 9999)]))


def _expr(rng, ops, depth, parens, unary, power=False):
    if depth <= 0 or rng.random() < 0.3:
        x = _num(rng)
        if unary and rng.random() < 0.2:
            x = "-" * rng.randint(1, 2) + x
        return x
    if power and rng.random() < 0.3:
        base = _expr(rng, ops, 0, parens, False)
        e = rng.choice(["2", "3", "0", "1", "-1", "70", "2^2", "-2"])
        s = f"{base}^{e}"
        return f"-{s}" if unary and rng.random() < 0.3 else s
    op = rng.choice(ops)
    left, right = _expr(rng, ops, depth - 1, parens, unary, power), _expr(rng, ops, depth - 1, parens, unary, power)
    s = f"{left}{rng.choice(['', ' '])}{op}{rng.choice(['', ' '])}{right}"
    if parens and rng.random() < 0.4:
        s = f"({s})"
        if unary and rng.random() < 0.3:
            s = "-" + s
    return s


def _lines(rng, make, n=(3, 7)):
    return "\n".join(make() for _ in range(rng.randint(*n))) + "\n"


def _calc_nonzero(rng, ops, depth, parens, unary, power=False):
    for _ in range(50):
        e = _expr(rng, ops, depth, parens, unary, power)
        if "/" not in e and "%" not in e:
            return e
        if not any(z in e for z in ("/0", "% 0", "/ 0", "%0")):
            return e
    return "1+1"


CALC = Program("calc", CALC_DOCS, CALC_SRC, [
    Feature("add_sub", "+ and - on integer literals",
            lambda r: _lines(r, lambda: _expr(r, ["+", "-"], 3, False, False))),
    Feature("mul_div_mod", "* / % with C-style truncation and precedence",
            lambda r: _lines(r, lambda: _calc_nonzero(r, ["+", "-", "*", "/", "%"], 3, False, False))),
    Feature("parens_unary", "parentheses and unary minus",
            lambda r: _lines(r, lambda: _calc_nonzero(r, ["+", "-", "*", "/", "%"], 4, True, True))),
    Feature("errors", "malformed lines and division by zero print error; blank lines skipped",
            lambda r: _lines(r, lambda: r.choice(["3 +", "(2", "2 2", "4 / 0", "a+1", "5 % (3-3)", ")", "1 + (2 * 3",
                                                 "", "7 - - 2", "*5", "8/(1-1)", _expr(r, ["+", "*"], 2, True, True)]))),
    Feature("power", "^ right associative, tighter than unary minus, exponent limits",
            lambda r: _lines(r, lambda: _calc_nonzero(r, ["+", "-", "*"], 3, True, True, power=True))),
])


# ============================================================================ kvdb
KVDB_SRC = r'''
import re, sys
db, tx, out = {}, [], []
INT = re.compile(r"^-?[0-9]+$")
def setv(k, v):
    if tx and k not in tx[-1]:
        tx[-1][k] = db.get(k)
    if v is None:
        db.pop(k, None)
    else:
        db[k] = v
for line in sys.stdin.read().split("\n"):
    p = line.split()
    if not p:
        continue
    cmd, a = p[0].upper(), p[1:]
    if cmd == "SET" and len(a) == 2:
        setv(a[0], a[1])
    elif cmd == "GET" and len(a) == 1:
        out.append(db.get(a[0], "NULL"))
    elif cmd == "DEL" and len(a) == 1:
        setv(a[0], None)
    elif cmd == "COUNT" and len(a) == 1:
        out.append(str(sum(1 for v in db.values() if v == a[0])))
    elif cmd == "INCR" and len(a) == 1:
        cur = db.get(a[0], "0")
        if not INT.match(cur):
            out.append("ERR")
        else:
            nv = str(int(cur) + 1); setv(a[0], nv); out.append(nv)
    elif cmd == "BEGIN" and not a:
        tx.append({})
    elif cmd == "ROLLBACK" and not a:
        if not tx:
            out.append("NO TRANSACTION")
        else:
            for k, v in tx.pop().items():
                if v is None:
                    db.pop(k, None)
                else:
                    db[k] = v
    elif cmd == "COMMIT" and not a:
        if not tx:
            out.append("NO TRANSACTION")
        else:
            tx.clear()
    else:
        out.append("ERR")
sys.stdout.write("\n".join(out) + ("\n" if out else ""))
'''

KVDB_DOCS = """kvdb - in-memory key-value store driven by commands on standard input, one per line.
Blank lines are ignored. Keys and values are single words (case-sensitive); command names are case-insensitive.
  SET key value   store value under key (no output)
  GET key         print the value, or NULL if the key is absent
  DEL key         remove key (no output; removing an absent key is fine)
  COUNT value     print how many keys currently hold exactly this value
  INCR key        treat the value as an integer (absent = 0), add 1, store and print the new value;
                  if the value is not an integer (optional '-' then digits only), print ERR and change nothing
  BEGIN           open a transaction; transactions nest
  ROLLBACK        undo every change made since the most recent open BEGIN and close it;
                  print NO TRANSACTION if none is open
  COMMIT          make all changes permanent and close ALL open transactions; NO TRANSACTION if none is open
Any other command, or a wrong number of arguments, prints ERR and changes nothing."""


def _kv_cmds(rng, kinds, n=(6, 14)):
    keys, vals = ["a", "b", "c", "x1", "Key"], ["1", "2", "-3", "07", "v", "hello", "1"]
    lines, depth = [], 0
    for _ in range(rng.randint(*n)):
        kind = rng.choice(kinds)
        k = rng.choice(keys)
        if kind == "set":
            lines.append(f"SET {k} {rng.choice(vals)}")
        elif kind == "get":
            lines.append(f"GET {k}")
        elif kind == "del":
            lines.append(f"DEL {k}")
        elif kind == "count":
            lines.append(f"COUNT {rng.choice(vals)}")
        elif kind == "incr":
            lines.append(f"INCR {k}")
        elif kind == "begin":
            lines.append("BEGIN"); depth += 1
        elif kind == "rollback":
            lines.append("ROLLBACK"); depth = max(0, depth - 1)
        elif kind == "commit":
            lines.append("COMMIT"); depth = 0
        elif kind == "bad":
            lines.append(rng.choice(["get a", "Set k v", "SET onlykey", "FOO bar", "GET", "begin", "rollback x", "COUNT"]))
    return "\n".join(lines) + "\n"


KVDB = Program("kvdb", KVDB_DOCS, KVDB_SRC, [
    Feature("set_get_del", "SET, GET, DEL", lambda r: _kv_cmds(r, ["set", "get", "del", "get"])),
    Feature("count", "COUNT", lambda r: _kv_cmds(r, ["set", "get", "del", "count", "count"])),
    Feature("incr", "INCR with integer rules", lambda r: _kv_cmds(r, ["set", "get", "incr", "incr", "count"])),
    Feature("rollback", "nested BEGIN / ROLLBACK", lambda r: _kv_cmds(r, ["set", "get", "del", "incr", "begin", "rollback", "rollback"], (8, 18))),
    Feature("commit_errors", "COMMIT, case-insensitivity, ERR", lambda r: _kv_cmds(r, ["set", "get", "begin", "rollback", "commit", "bad", "incr"], (8, 18))),
])


# ============================================================================ textfmt
TEXTFMT_SRC = r'''
import sys
def chunks(w, width):
    return [w[i:i + width] for i in range(0, len(w), width)]
def wrap(words, width):
    lines, cur = [], []
    for w in words:
        for piece in (chunks(w, width) if len(w) > width else [w]):
            if cur and len(" ".join(cur)) + 1 + len(piece) > width:
                lines.append(cur); cur = []
            cur.append(piece)
    if cur:
        lines.append(cur)
    return lines
def render(line, width, mode, last):
    s = " ".join(line)
    if mode == "right":
        return " " * (width - len(s)) + s
    if mode == "center":
        return " " * ((width - len(s)) // 2) + s
    if mode == "justify" and not last and len(line) > 1:
        gaps = len(line) - 1
        base, extra = divmod(width - sum(map(len, line)), gaps)
        return "".join(w + " " * (base + (1 if i < extra else 0)) for i, w in enumerate(line[:-1])) + line[-1]
    return s
data = sys.stdin.read().split("\n")
head = data[0].split()
width, mode = int(head[0]), (head[1] if len(head) > 1 else "left")
paras, cur = [], []
for line in data[1:]:
    if line.strip() == "":
        if cur:
            paras.append(cur); cur = []
    else:
        cur.extend(line.split())
if cur:
    paras.append(cur)
out = []
for k, p in enumerate(paras):
    if k:
        out.append("")
    ls = wrap(p, width)
    for i, l in enumerate(ls):
        out.append(render(l, width, mode, i == len(ls) - 1))
sys.stdout.write("\n".join(out) + ("\n" if out else ""))
'''

TEXTFMT_DOCS = """textfmt - paragraph formatter.
The first input line is the header: WIDTH [MODE], where WIDTH is a positive integer and MODE is one of
left (default), right, center, justify. The rest of the input is text. Paragraphs are separated by one
or more blank (or whitespace-only) lines; inside a paragraph, line breaks and runs of spaces/tabs only
separate words.
Each paragraph is filled greedily: as many words as fit on a line of at most WIDTH characters with
single spaces between them. A word longer than WIDTH is cut into pieces of exactly WIDTH characters
(the last piece may be shorter), and each piece is placed like a word.
  left     lines as filled, no trailing spaces
  right    lines padded on the left with spaces to exactly WIDTH
  center   lines padded on the left with floor((WIDTH - length) / 2) spaces, no trailing spaces
  justify  every line except a paragraph's last line and except single-word lines is stretched to
           exactly WIDTH by widening the gaps between words; extra spaces go to the leftmost gaps
Paragraphs in the output are separated by exactly one empty line. No output for empty text."""

_WORDS = ("the quick brown fox jumps over lazy dog a an of to in is it be at on we us go no so do "
          "elephant antidisestablishment supercalifragilistic formatting paragraph justify").split()


def _text(rng, width, paragraphs=(1, 1), long_words=False, messy=False):
    paras = []
    for _ in range(rng.randint(*paragraphs)):
        words = [rng.choice(_WORDS if long_words else [w for w in _WORDS if len(w) <= width]) for _ in range(rng.randint(3, 25))]
        lines, cur = [], []
        for w in words:
            cur.append(w)
            if rng.random() < 0.2:
                lines.append((" " * rng.randint(1, 3) if messy else " ").join(cur)); cur = []
        lines.append(" ".join(cur))
        paras.append("\n".join(l for l in lines if l))
    sep = "\n\n" if not messy else rng.choice(["\n\n", "\n\n\n", "\n  \n"])
    return sep.join(paras)


def _fmt(rng, modes, **kw):
    width = rng.randint(12, 40)
    return f"{width} {rng.choice(modes)}\n" + _text(rng, width, **kw) + "\n"


TEXTFMT = Program("textfmt", TEXTFMT_DOCS, TEXTFMT_SRC, [
    Feature("left", "greedy left fill of one paragraph", lambda r: _fmt(r, ["left"])),
    Feature("paragraphs", "several paragraphs, messy spacing, default mode",
            lambda r: (lambda s: s.replace(" left\n", "\n", 1) if r.random() < 0.3 else s)(_fmt(r, ["left"], paragraphs=(2, 4), messy=True))),
    Feature("right_center", "right and center alignment", lambda r: _fmt(r, ["right", "center"], paragraphs=(1, 3))),
    Feature("justify", "full justification", lambda r: _fmt(r, ["justify"], paragraphs=(1, 3))),
    Feature("long_words", "words longer than WIDTH", lambda r: _fmt(r, ["left", "right", "center", "justify"], paragraphs=(1, 3), long_words=True)),
])

PROGRAMS = {p.id: p for p in (CALC, KVDB, TEXTFMT)}
