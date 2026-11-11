"""A small, safe expression language for database formula properties.

    prop("Price") * prop("Quantity")
    if(prop("Done"), "✓", "Due " + formatDate(prop("Due"), "MMM D"))
    dateBetween(prop("Deadline"), now(), "days") < 7 and not prop("Done")

Values are numbers (float), strings, booleans, dates, lists or None.
Errors raise FormulaError, which callers show instead of a value.
"""
import datetime as dt
import math
import re

from django.utils import timezone


class FormulaError(Exception):
    pass


_TOKEN = re.compile(
    r"""\s*(?:
        (?P<num>\d+(?:\.\d*)?|\.\d+)
      | (?P<str>"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')
      | (?P<name>[A-Za-z_][A-Za-z0-9_]*)
      | (?P<op>==|!=|>=|<=|&&|\|\||[-+*/%^()<>,!?:])
    )""",
    re.X,
)

# Binding power for infix operators.
_INFIX = {
    "?": 1, "or": 2, "||": 2, "and": 3, "&&": 3,
    "==": 4, "!=": 4, "<": 5, ">": 5, "<=": 5, ">=": 5,
    "+": 6, "-": 6, "*": 7, "/": 7, "%": 7, "^": 9,
}


def tokenize(src: str) -> list[tuple[str, object]]:
    out, i = [], 0
    src = src.rstrip()
    while i < len(src):
        m = _TOKEN.match(src, i)
        if not m or m.end() == i:
            raise FormulaError(f"Unexpected character “{src[i:].strip()[:1]}”")
        i = m.end()
        if m["num"]:
            out.append(("num", float(m["num"])))
        elif m["str"]:
            body = m["str"][1:-1]
            out.append(("str", re.sub(r"\\(.)", r"\1", body)))
        elif m["name"]:
            word = m["name"]
            if word in ("true", "false"):
                out.append(("val", word == "true"))
            elif word in ("and", "or", "not"):
                out.append(("op", word))
            else:
                out.append(("name", word))
        else:
            out.append(("op", m["op"]))
    out.append(("end", None))
    return out


class Parser:
    def __init__(self, src: str):
        self.toks = tokenize(src)
        self.i = 0

    def peek(self):
        return self.toks[self.i]

    def take(self, kind=None, value=None):
        tok = self.toks[self.i]
        if (kind and tok[0] != kind) or (value is not None and tok[1] != value):
            want = value or kind
            got = tok[1] if tok[0] != "end" else "end of formula"
            raise FormulaError(f"Expected “{want}” but found “{got}”")
        self.i += 1
        return tok

    def parse(self):
        node = self.expr(0)
        self.take("end")
        return node

    def expr(self, rbp: int):
        left = self.prefix()
        while True:
            kind, val = self.peek()
            if kind != "op" or val not in _INFIX or _INFIX[val] <= rbp:
                return left
            self.take()
            if val == "?":
                then = self.expr(0)
                self.take("op", ":")
                other = self.expr(0)
                left = ("if", left, then, other)
            else:
                # ^ is right-associative
                right = self.expr(_INFIX[val] - (1 if val == "^" else 0))
                left = ("bin", val, left, right)

    def prefix(self):
        kind, val = self.take()
        if kind in ("num", "str", "val"):
            return ("lit", val)
        if kind == "op" and val in ("-", "+"):
            return ("neg" if val == "-" else "pos", self.expr(8))
        if kind == "op" and val in ("!", "not"):
            return ("not", self.expr(3))
        if kind == "op" and val == "(":
            node = self.expr(0)
            self.take("op", ")")
            return node
        if kind == "name":
            if self.peek() == ("op", "("):
                self.take()
                args = []
                if self.peek() != ("op", ")"):
                    args.append(self.expr(0))
                    while self.peek() == ("op", ","):
                        self.take()
                        args.append(self.expr(0))
                self.take("op", ")")
                return ("call", val, args)
            if val in CONSTANTS:
                return ("lit", CONSTANTS[val])
            raise FormulaError(f"Unknown name “{val}”. Use prop(\"{val}\") for properties.")
        raise FormulaError(f"Unexpected “{val if kind != 'end' else 'end of formula'}”")


CONSTANTS = {"pi": math.pi, "e": math.e}

# --------------------------------------------------------------- helpers


def truthy(v) -> bool:
    if isinstance(v, list):
        return len(v) > 0
    return bool(v)


def to_num(v):
    if v is None or v == "":
        return 0.0
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v.strip())
        except ValueError:
            raise FormulaError(f"“{v}” is not a number")
    if isinstance(v, list):
        return float(len(v))
    raise FormulaError("Expected a number")


def to_str(v) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float):
        return str(int(v)) if v.is_integer() and abs(v) < 1e15 else f"{v:.10g}"
    if isinstance(v, dt.datetime):
        return v.strftime("%Y-%m-%d %H:%M")
    if isinstance(v, dt.date):
        return v.isoformat()
    if isinstance(v, list):
        return ", ".join(to_str(x) for x in v)
    return str(v)


def to_date(v):
    if v is None or v == "":
        return None
    if isinstance(v, dt.datetime):
        return v
    if isinstance(v, dt.date):
        return dt.datetime(v.year, v.month, v.day, tzinfo=dt.UTC)
    if isinstance(v, str):
        try:
            d = dt.datetime.fromisoformat(v.replace("Z", "+00:00"))
        except ValueError:
            raise FormulaError(f"“{v}” is not a date")
        return d if d.tzinfo else d.replace(tzinfo=dt.UTC)
    raise FormulaError("Expected a date")


_UNITS = {
    "years": 365.2425 * 86400, "months": 30.436875 * 86400, "weeks": 7 * 86400,
    "days": 86400, "hours": 3600, "minutes": 60, "seconds": 1,
}


def _unit(u) -> str:
    u = to_str(u).lower()
    if not u.endswith("s"):
        u += "s"
    if u not in _UNITS:
        raise FormulaError(f"Unknown unit “{u}”. Use years, months, weeks, days, hours or minutes.")
    return u


def _add(d, n, unit):
    d, n, unit = to_date(d), to_num(n), _unit(unit)
    if d is None:
        return None
    if unit in ("years", "months"):
        months = int(n) * (12 if unit == "years" else 1)
        y, m = divmod(d.month - 1 + months, 12)
        year, month = d.year + y, m + 1
        last = [31, 29 if year % 4 == 0 and (year % 100 or year % 400 == 0) else 28, 31, 30, 31, 30,
                31, 31, 30, 31, 30, 31][month - 1]
        return d.replace(year=year, month=month, day=min(d.day, last))
    return d + dt.timedelta(seconds=n * _UNITS[unit])


def _format_date(d, fmt="YYYY-MM-DD"):
    d = to_date(d)
    if d is None:
        return ""
    fmt = to_str(fmt)
    table = {
        "YYYY": "%Y", "YY": "%y", "MMMM": "%B", "MMM": "%b", "MM": "%m", "M": str(d.month),
        "DD": "%d", "D": str(d.day), "dddd": "%A", "ddd": "%a", "HH": "%H", "hh": "%I",
        "mm": "%M", "A": "%p",
    }
    out = re.sub(r"YYYY|YY|MMMM|MMM|MM|M|DD|D|dddd|ddd|HH|hh|mm|A",
                 lambda m: table[m.group(0)], fmt)
    return d.strftime(out)


def _between(a, b, unit):
    a, b = to_date(a), to_date(b)
    if a is None or b is None:
        return None
    return float(math.trunc((a - b).total_seconds() / _UNITS[_unit(unit)]))


def _round(x, places=0):
    p = int(to_num(places))
    return float(round(to_num(x), p))


def _empty(v):
    return v is None or v == "" or v == [] or v is False


def _nums(args):
    flat = []
    for a in args:
        flat.extend(a if isinstance(a, list) else [a])
    return [to_num(x) for x in flat if x is not None and x != ""]


FUNCTIONS = {
    "abs": lambda x: abs(to_num(x)),
    "round": _round,
    "floor": lambda x: float(math.floor(to_num(x))),
    "ceil": lambda x: float(math.ceil(to_num(x))),
    "sqrt": lambda x: math.sqrt(to_num(x)),
    "pow": lambda a, b: to_num(a) ** to_num(b),
    "min": lambda *a: min(_nums(a)) if _nums(a) else None,
    "max": lambda *a: max(_nums(a)) if _nums(a) else None,
    "sum": lambda *a: sum(_nums(a)),
    "mean": lambda *a: (sum(_nums(a)) / len(_nums(a))) if _nums(a) else None,
    "toNumber": lambda x: to_num(x),
    "concat": lambda *a: "".join(to_str(x) for x in a),
    "join": lambda lst, sep=", ": to_str(sep).join(to_str(x) for x in (lst if isinstance(lst, list) else [lst])),
    "length": lambda x: float(len(x) if isinstance(x, list) else len(to_str(x))),
    "lower": lambda s: to_str(s).lower(),
    "upper": lambda s: to_str(s).upper(),
    "trim": lambda s: to_str(s).strip(),
    "contains": lambda s, sub: (to_str(sub) in [to_str(x) for x in s]) if isinstance(s, list) else to_str(sub).lower() in to_str(s).lower(),
    "replace": lambda s, a, b: to_str(s).replace(to_str(a), to_str(b)),
    "slice": lambda s, a, b=None: to_str(s)[int(to_num(a)): None if b is None else int(to_num(b))],
    "format": to_str,
    "empty": _empty,
    "now": lambda: timezone.now(),
    "today": lambda: timezone.now().replace(hour=0, minute=0, second=0, microsecond=0),
    "dateAdd": _add,
    "dateSubtract": lambda d, n, u: _add(d, -to_num(n), u),
    "dateBetween": _between,
    "formatDate": _format_date,
    "year": lambda d: float(to_date(d).year) if to_date(d) else None,
    "month": lambda d: float(to_date(d).month) if to_date(d) else None,
    "day": lambda d: float(to_date(d).isoweekday() % 7) if to_date(d) else None,
    "date": lambda d: float(to_date(d).day) if to_date(d) else None,
}
LAZY = {"if", "ifs", "prop", "and", "or", "not"}


class Evaluator:
    def __init__(self, lookup):
        # lookup(name) -> value of the named property for the current row
        self.lookup = lookup
        self.steps = 0

    def run(self, node):
        self.steps += 1
        if self.steps > 20000:
            raise FormulaError("Formula is too complex")
        kind = node[0]
        if kind == "lit":
            return node[1]
        if kind == "neg":
            return -to_num(self.run(node[1]))
        if kind == "pos":
            return to_num(self.run(node[1]))
        if kind == "not":
            return not truthy(self.run(node[1]))
        if kind == "if":
            return self.run(node[2]) if truthy(self.run(node[1])) else self.run(node[3])
        if kind == "bin":
            return self.binary(node[1], node[2], node[3])
        if kind == "call":
            return self.call(node[1], node[2])
        raise FormulaError("Invalid formula")

    def binary(self, op, a, b):
        if op in ("and", "&&"):
            return truthy(self.run(a)) and truthy(self.run(b))
        if op in ("or", "||"):
            return truthy(self.run(a)) or truthy(self.run(b))
        x, y = self.run(a), self.run(b)
        if op == "+":
            if isinstance(x, str) or isinstance(y, str):
                return to_str(x) + to_str(y)
            return to_num(x) + to_num(y)
        if op == "-":
            if isinstance(x, (dt.date, dt.datetime)) and isinstance(y, (dt.date, dt.datetime)):
                return (to_date(x) - to_date(y)).total_seconds() / 86400
            return to_num(x) - to_num(y)
        if op == "*":
            return to_num(x) * to_num(y)
        if op == "/":
            d = to_num(y)
            if d == 0:
                raise FormulaError("Division by zero")
            return to_num(x) / d
        if op == "%":
            d = to_num(y)
            if d == 0:
                raise FormulaError("Division by zero")
            return math.fmod(to_num(x), d)
        if op == "^":
            return to_num(x) ** to_num(y)
        if op in ("==", "!="):
            eq = _compare_key(x) == _compare_key(y)
            return eq if op == "==" else not eq
        kx, ky = _compare_key(x), _compare_key(y)
        try:
            return {"<": kx < ky, ">": kx > ky, "<=": kx <= ky, ">=": kx >= ky}[op]
        except TypeError:
            raise FormulaError("Cannot compare these values")

    def call(self, name, args):
        if name == "prop":
            if len(args) != 1 or args[0][0] != "lit" or not isinstance(args[0][1], str):
                raise FormulaError('prop() takes a property name in quotes, e.g. prop("Price")')
            return self.lookup(args[0][1])
        if name == "if":
            if len(args) != 3:
                raise FormulaError("if() takes 3 arguments: condition, then, else")
            return self.run(args[1]) if truthy(self.run(args[0])) else self.run(args[2])
        if name == "ifs":
            for i in range(0, len(args) - 1, 2):
                if truthy(self.run(args[i])):
                    return self.run(args[i + 1])
            return self.run(args[-1]) if len(args) % 2 else None
        if name in ("and", "or"):
            vals = (truthy(self.run(a)) for a in args)
            return all(vals) if name == "and" else any(vals)
        if name == "not":
            return not truthy(self.run(args[0])) if args else True
        fn = FUNCTIONS.get(name)
        if not fn:
            raise FormulaError(f"Unknown function “{name}”")
        try:
            return fn(*[self.run(a) for a in args])
        except TypeError:
            raise FormulaError(f"Wrong number of arguments for {name}()")
        except (ValueError, OverflowError) as e:
            raise FormulaError(f"{name}(): {e}")


def _compare_key(v):
    if isinstance(v, (dt.date, dt.datetime)):
        return to_date(v).timestamp()
    if isinstance(v, bool):
        return float(v)
    if isinstance(v, list):
        return to_str(v)
    return v if v is not None else ""


_cache: dict[str, object] = {}


def compile_formula(src: str):
    if src not in _cache:
        if len(_cache) > 500:
            _cache.clear()
        try:
            _cache[src] = Parser(src).parse()
        except FormulaError as e:
            _cache[src] = e
    node = _cache[src]
    if isinstance(node, FormulaError):
        raise node
    return node


def to_json(v):
    """Formula result as a JSON-friendly value."""
    if isinstance(v, float):
        if math.isnan(v) or math.isinf(v):
            return None
        return round(v, 10)
    if isinstance(v, dt.datetime):
        return v.isoformat()
    if isinstance(v, dt.date):
        return v.isoformat()
    if isinstance(v, list):
        return [to_json(x) for x in v]
    return v
