"""Formula fields: a value worked out from a record's other fields when it is
read, never stored.

An expression is a small, safe language that looks like arithmetic:
`end - start`, `mass / height ** 2`, `depth_ft * 0.3048`,
`concat(site, "-", code)`, `"deep" if depth > 200 else "shallow"`. It is
parsed with Python's `ast` and only the node kinds listed here are accepted:
there is no `eval`, no attribute access other than `ref.field` (a field of
the record a single link points at), no subscripts, comprehensions, lambdas
or keyword arguments, and only the functions in `FUNCTIONS` can be called.

Pure: the service hands in values, their field types and the result type.

- `parse(source)` checks the expression's shape (`ValidationError`).
- `infer(formula, types)` checks that the names exist and the types fit,
  and says what kind of value comes out (`ValidationError`).
- `compute(formula, values, types, result, decimals)` works it out for one
  record: `(value, None)`, or `(None, problem)` when it can't (dividing by
  zero, a value of the wrong kind). A blank input gives a blank result,
  unless `coalesce` supplies another.
- `rename(source, old, new, via)` rewrites a field's name where the
  expression uses it; `uses(formula, name, via)` says whether it does.
"""

from __future__ import annotations

import ast
import functools
import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable

from civex.domain.exceptions import ValidationError

#: What a formula's value can be (the `result` restriction).
RESULT_TYPES = ("float", "integer", "string", "boolean", "date", "datetime")

#: Limits, so an expression can't be made expensive to read.
MAX_SOURCE = 1000
MAX_NODES = 200
MAX_TEXT = 10_000
MAX_EXPONENT = 1000
MAX_DECIMALS = 10

# What a value is, for type checking: one of these, or "any" when it can't
# be known before reading (only from `coalesce` over mixed kinds).
NUMBER, TEXT, BOOL, DATE, DATETIME, LIST, ANY = (
    "number",
    "text",
    "boolean",
    "date",
    "datetime",
    "list",
    "any",
)

#: What a field of each type is inside a formula. Types left out (files,
#: links, locations) can't be used, except a link as the first part of
#: `link.field`.
KIND_OF_DTYPE: dict[str, str] = {
    "integer": NUMBER,
    "float": NUMBER,
    "string": TEXT,
    "longtext": TEXT,
    "enum": TEXT,
    "url": TEXT,
    "boolean": BOOL,
    "date": DATE,
    "datetime": DATETIME,
    "tags": LIST,
}

#: What each result type is inside another formula.
KIND_OF_RESULT: dict[str, str] = {
    "float": NUMBER,
    "integer": NUMBER,
    "string": TEXT,
    "boolean": BOOL,
    "date": DATE,
    "datetime": DATETIME,
}

#: The result type a formula gets when none is given, from what it gives.
RESULT_OF_KIND: dict[str, str] = {
    NUMBER: "float",
    TEXT: "string",
    BOOL: "boolean",
    DATE: "date",
    DATETIME: "datetime",
}


class FormulaError(Exception):
    """A formula that can't be worked out for one record (the value is left
    blank and the reason shown)."""


@dataclass(frozen=True)
class Formula:
    source: str
    tree: ast.expr
    #: Every name it reads, in order: plain field names and `link.field`.
    names: tuple[str, ...]


# -- functions --------------------------------------------------------------


def _num(v: Any, fn: str) -> float | int:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise FormulaError(f"{fn}() needs a number, got {_shown(v)}")
    return v


def _text(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    if isinstance(v, list):
        return ", ".join(_text(x) for x in v)
    return str(v)


def _capped(s: str) -> str:
    if len(s) > MAX_TEXT:
        raise FormulaError(f"the text would be longer than {MAX_TEXT} characters")
    return s


def _as_date(v: Any, fn: str) -> date:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    if isinstance(v, str):
        try:
            return date.fromisoformat(v)
        except ValueError:
            raise FormulaError(
                f"{fn}() needs a full date (year, month and day), got {v!r}"
            ) from None
    raise FormulaError(f"{fn}() needs a date, got {_shown(v)}")


def _as_moment(v: Any, fn: str) -> datetime:
    if isinstance(v, datetime):
        return v
    return datetime.combine(_as_date(v, fn), datetime.min.time(), timezone.utc)


def _date_part(v: Any, fn: str, part: int) -> int:
    if isinstance(v, (date, datetime)):
        return (v.year, v.month, v.day)[part]
    if isinstance(v, str):
        # A date known only to the year or month still has those parts.
        pieces = v.split("-")
        if len(pieces) > part and pieces[part].isdigit():
            return int(pieces[part])
        raise FormulaError(f"{fn}() can't read that from {v!r}")
    raise FormulaError(f"{fn}() needs a date, got {_shown(v)}")


def _round(x: Any, n: Any = 0) -> float | int:
    x = _num(x, "round")
    n = _num(n, "round")
    if not float(n).is_integer() or not 0 <= n <= MAX_DECIMALS:
        raise FormulaError(f"round() takes 0 to {MAX_DECIMALS} decimal places")
    return round(x) if n == 0 else round(x, int(n))


def _log(x: Any, base: Any = None) -> float:
    x = _num(x, "log")
    if x <= 0:
        raise FormulaError("log() needs a number above zero")
    if base is None:
        return math.log(x)
    base = _num(base, "log")
    if base <= 0 or base == 1:
        raise FormulaError("log()'s base must be above zero and not 1")
    return math.log(x, base)


def _sqrt(x: Any) -> float:
    x = _num(x, "sqrt")
    if x < 0:
        raise FormulaError("sqrt() of a negative number")
    return math.sqrt(x)


def _exp(x: Any) -> float:
    try:
        return math.exp(_num(x, "exp"))
    except OverflowError:
        raise FormulaError("exp() is too large") from None


def _len(v: Any) -> int:
    if isinstance(v, (str, list)):
        return len(v)
    raise FormulaError(f"len() needs text or a list, got {_shown(v)}")


def _case(fn: str, op: Callable[[str], str]) -> Callable[[Any], str]:
    def call(v: Any) -> str:
        if not isinstance(v, str):
            raise FormulaError(f"{fn}() needs text, got {_shown(v)}")
        return op(v)

    return call


def _between(unit_seconds: int, fn: str) -> Callable[[Any, Any], float | int]:
    def call(a: Any, b: Any) -> float | int:
        if isinstance(a, datetime) or isinstance(b, datetime):
            seconds = (_as_moment(b, fn) - _as_moment(a, fn)).total_seconds()
            return seconds / unit_seconds
        days = (_as_date(b, fn) - _as_date(a, fn)).days
        return days if unit_seconds == 86400 else days * 86400 / unit_seconds

    return call


def _date_add(d: Any, days: Any) -> date | datetime:
    n = _num(days, "date_add")
    if abs(n) > 3_000_000:
        raise FormulaError("date_add() moves too far")
    try:
        if isinstance(d, datetime):
            return d + timedelta(days=n)
        if not float(n).is_integer():
            raise FormulaError(
                "date_add() adds whole days to a date (use a date and time "
                "for parts of a day)"
            )
        return _as_date(d, "date_add") + timedelta(days=int(n))
    except OverflowError:
        raise FormulaError("date_add() goes past the years a date can have") from None


def _min_max(fn: str, pick: Callable[..., Any]) -> Callable[..., Any]:
    def call(*args: Any) -> Any:
        try:
            return pick(args)
        except TypeError:
            raise FormulaError(f"{fn}() can't compare those values") from None

    return call


def _concat(*args: Any) -> str:
    return _capped("".join(_text(a) for a in args))


@dataclass(frozen=True)
class Function:
    call: Callable[..., Any]
    #: Kinds of the arguments (the last repeats for `variadic`); ANY = any.
    args: tuple[str, ...]
    #: The kind of what it gives (ANY = the same as its first argument).
    gives: str
    #: How many arguments may be left off the end.
    optional: int = 0
    variadic: bool = False
    #: Plain words for the field editor.
    help: str = ""


FUNCTIONS: dict[str, Function] = {
    "round": Function(
        _round, (NUMBER, NUMBER), NUMBER, 1, help="round(x, places): round a number"
    ),
    "abs": Function(lambda x: abs(_num(x, "abs")), (NUMBER,), NUMBER, help="abs(x)"),
    "min": Function(
        _min_max("min", min), (ANY, ANY), ANY, variadic=True, help="min(a, b, ...)"
    ),
    "max": Function(
        _min_max("max", max), (ANY, ANY), ANY, variadic=True, help="max(a, b, ...)"
    ),
    "sqrt": Function(_sqrt, (NUMBER,), NUMBER, help="sqrt(x): square root"),
    "log": Function(
        _log, (NUMBER, NUMBER), NUMBER, 1, help="log(x, base): natural log by default"
    ),
    "exp": Function(_exp, (NUMBER,), NUMBER, help="exp(x)"),
    "floor": Function(
        lambda x: math.floor(_num(x, "floor")), (NUMBER,), NUMBER, help="floor(x)"
    ),
    "ceil": Function(
        lambda x: math.ceil(_num(x, "ceil")), (NUMBER,), NUMBER, help="ceil(x)"
    ),
    "coalesce": Function(
        lambda *a: next((v for v in a if v is not None), None),
        (ANY, ANY),
        ANY,
        variadic=True,
        help="coalesce(a, b, ...): the first that isn't blank",
    ),
    "concat": Function(
        _concat, (ANY, ANY), TEXT, variadic=True, help="concat(a, b, ...): join as text"
    ),
    "str": Function(lambda v: _capped(_text(v)), (ANY,), TEXT, help="str(x): as text"),
    "upper": Function(_case("upper", str.upper), (TEXT,), TEXT, help="upper(text)"),
    "lower": Function(_case("lower", str.lower), (TEXT,), TEXT, help="lower(text)"),
    "len": Function(_len, (ANY,), NUMBER, help="len(text or tags)"),
    "days_between": Function(
        _between(86400, "days_between"),
        (ANY, ANY),
        NUMBER,
        help="days_between(start, end)",
    ),
    "hours_between": Function(
        _between(3600, "hours_between"),
        (ANY, ANY),
        NUMBER,
        help="hours_between(start, end)",
    ),
    "year": Function(
        lambda d: _date_part(d, "year", 0), (ANY,), NUMBER, help="year(date)"
    ),
    "month": Function(
        lambda d: _date_part(d, "month", 1), (ANY,), NUMBER, help="month(date)"
    ),
    "day": Function(
        lambda d: _date_part(d, "day", 2), (ANY,), NUMBER, help="day(date)"
    ),
    "date_add": Function(
        _date_add, (ANY, NUMBER), ANY, help="date_add(date, days): a later date"
    ),
}

#: Which arguments (by position) must be a date or a date and time.
_DATE_ARGS: dict[str, tuple[int, ...]] = {
    "days_between": (0, 1),
    "hours_between": (0, 1),
    "year": (0,),
    "month": (0,),
    "day": (0,),
    "date_add": (0,),
}


# -- parsing ----------------------------------------------------------------

_BINOPS: dict[type, str] = {
    ast.Add: "+",
    ast.Sub: "-",
    ast.Mult: "*",
    ast.Div: "/",
    ast.FloorDiv: "//",
    ast.Mod: "%",
    ast.Pow: "**",
}
_CMPOPS: dict[type, Callable[[Any, Any], bool]] = {
    ast.Eq: lambda a, b: a == b,
    ast.NotEq: lambda a, b: a != b,
    ast.Lt: lambda a, b: a < b,
    ast.LtE: lambda a, b: a <= b,
    ast.Gt: lambda a, b: a > b,
    ast.GtE: lambda a, b: a >= b,
}


def _name_of(node: ast.expr) -> str | None:
    """`field` or `link.field` for a name node, else None."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
        return f"{node.value.id}.{node.attr}"
    return None


def _check_name(name: str) -> None:
    for part in name.split("."):
        if part.startswith("_"):
            raise ValidationError(f"'{name}' can't be used in a formula")


def _check_node(node: ast.AST) -> None:
    """Refuse anything that isn't part of the language."""
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or isinstance(node.value, (int, float, str)):
            if isinstance(node.value, str) and len(node.value) > MAX_TEXT:
                raise ValidationError("A piece of text in the formula is too long")
            return
        raise ValidationError(f"{node.value!r} can't be used in a formula")
    if isinstance(node, ast.Name):
        _check_name(node.id)
        return
    if isinstance(node, ast.Attribute):
        if not isinstance(node.value, ast.Name):
            raise ValidationError(
                "Only a link's field can be reached with a dot (link.field), one step"
            )
        _check_name(f"{node.value.id}.{node.attr}")
        return
    if isinstance(node, ast.BinOp):
        if type(node.op) not in _BINOPS:
            raise ValidationError("That operator can't be used in a formula")
        return
    if isinstance(node, ast.UnaryOp):
        if not isinstance(node.op, (ast.USub, ast.UAdd, ast.Not)):
            raise ValidationError("That operator can't be used in a formula")
        return
    if isinstance(node, ast.BoolOp):
        return
    if isinstance(node, ast.Compare):
        if any(type(op) not in _CMPOPS for op in node.ops):
            raise ValidationError(
                "Compare with ==, !=, <, <=, > or >= (not 'in' or 'is')"
            )
        return
    if isinstance(node, ast.IfExp):
        return
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name):
            raise ValidationError("Only the formula functions can be called")
        fn = FUNCTIONS.get(node.func.id)
        if fn is None:
            raise ValidationError(
                f"There is no function '{node.func.id}'. Use one of: "
                + ", ".join(sorted(FUNCTIONS))
            )
        if node.keywords or any(isinstance(a, ast.Starred) for a in node.args):
            raise ValidationError(f"{node.func.id}() takes plain values only")
        least = len(fn.args) - fn.optional
        most = None if fn.variadic else len(fn.args)
        if len(node.args) < (1 if fn.variadic else least) or (
            most is not None and len(node.args) > most
        ):
            raise ValidationError(f"{fn.help or node.func.id}: wrong number of values")
        return
    if isinstance(node, (ast.operator, ast.unaryop, ast.boolop, ast.cmpop)):
        return
    if isinstance(node, (ast.Load, ast.Expression)):
        return
    raise ValidationError(f"{type(node).__name__} can't be used in a formula")


@functools.lru_cache(maxsize=512)
def parse(source: str) -> Formula:
    """The expression, checked for shape. Raises ValidationError."""
    if not isinstance(source, str) or not source.strip():
        raise ValidationError("A formula needs an expression")
    if len(source) > MAX_SOURCE:
        raise ValidationError(f"A formula can be at most {MAX_SOURCE} characters")
    try:
        tree = ast.parse(source.strip(), mode="eval")
    except SyntaxError as e:
        raise ValidationError(f"The formula can't be read: {e.msg}") from None
    count = 0
    names: list[str] = []
    for node in ast.walk(tree):
        count += 1
        if count > MAX_NODES:
            raise ValidationError("The formula is too long")
        _check_node(node)
    _collect_names(tree.body, names)
    return Formula(source.strip(), tree.body, tuple(dict.fromkeys(names)))


def _collect_names(node: ast.AST, into: list[str]) -> None:
    name = _name_of(node) if isinstance(node, ast.expr) else None
    if name is not None:
        into.append(name)
        return
    for child in ast.iter_child_nodes(node):
        if isinstance(node, ast.Call) and child is node.func:
            continue
        _collect_names(child, into)


# -- types ------------------------------------------------------------------


def infer(formula: Formula, kinds: dict[str, str]) -> str:
    """The kind of value `formula` gives, with each name's kind in `kinds`
    (see `KIND_OF_DTYPE`). Raises ValidationError for an unknown name or a
    value of the wrong kind."""
    return _infer(formula.tree, kinds)


def _infer(node: ast.expr, kinds: dict[str, str]) -> str:
    name = _name_of(node)
    if name is not None:
        if name not in kinds:
            raise ValidationError(f"There is no field '{name}' a formula here can use")
        return kinds[name]
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool):
            return BOOL
        return TEXT if isinstance(node.value, str) else NUMBER
    if isinstance(node, ast.UnaryOp):
        inner = _infer(node.operand, kinds)
        if isinstance(node.op, ast.Not):
            _want(inner, BOOL, "not")
            return BOOL
        _want(inner, NUMBER, "a minus sign")
        return NUMBER
    if isinstance(node, ast.BoolOp):
        for v in node.values:
            _want(_infer(v, kinds), BOOL, "and/or")
        return BOOL
    if isinstance(node, ast.Compare):
        sides = [_infer(node.left, kinds)] + [
            _infer(c, kinds) for c in node.comparators
        ]
        known = {s for s in sides if s != ANY}
        if len(known) > 1:
            raise ValidationError(
                "A comparison needs values of one kind (" + " and ".join(known) + ")"
            )
        return BOOL
    if isinstance(node, ast.IfExp):
        _want(_infer(node.test, kinds), BOOL, "the condition after 'if'")
        a, b = _infer(node.body, kinds), _infer(node.orelse, kinds)
        if ANY in (a, b) or a == b:
            return b if a == ANY else a
        raise ValidationError(
            f"Both sides of an 'if ... else' must give one kind of value ({a}, {b})"
        )
    if isinstance(node, ast.BinOp):
        a, b = _infer(node.left, kinds), _infer(node.right, kinds)
        op = _BINOPS[type(node.op)]
        if op == "+" and a == TEXT and b == TEXT:
            return TEXT
        if op == "-" and a in (DATE, DATETIME) and b in (DATE, DATETIME):
            raise ValidationError(
                "Subtract dates with days_between(start, end) or "
                "hours_between(start, end)"
            )
        _want(a, NUMBER, f"'{op}'")
        _want(b, NUMBER, f"'{op}'")
        return NUMBER
    if isinstance(node, ast.Call):
        assert isinstance(node.func, ast.Name)
        fname = node.func.id
        fn = FUNCTIONS[fname]
        got = [_infer(a, kinds) for a in node.args]
        for i, kind in enumerate(got):
            want = fn.args[min(i, len(fn.args) - 1)]
            if want != ANY:
                _want(kind, want, f"{fname}()")
            elif i in _DATE_ARGS.get(fname, ()) and kind not in (DATE, DATETIME, ANY):
                raise ValidationError(f"{fname}() needs a date, not {kind_words(kind)}")
        if fname in ("min", "max", "coalesce"):
            known = {k for k in got if k != ANY}
            if len(known) > 1:
                raise ValidationError(
                    f"{fname}() needs values of one kind ({', '.join(sorted(known))})"
                )
            return known.pop() if known else ANY
        if fname == "date_add":
            return got[0] if got[0] != ANY else DATE
        return fn.gives
    raise ValidationError("That can't be used in a formula")


def _want(kind: str, want: str, where: str) -> None:
    if kind not in (want, ANY):
        raise ValidationError(
            f"{where} needs {kind_words(want)}, not {kind_words(kind)}"
        )


def kind_words(kind: str) -> str:
    return {
        NUMBER: "a number",
        TEXT: "text",
        BOOL: "yes/no",
        DATE: "a date",
        DATETIME: "a date and time",
        LIST: "a list",
    }.get(kind, kind)


def fits(kind: str, result: str) -> bool:
    """Whether a value of `kind` can be given as a `result`."""
    if kind == ANY or result == "string":
        return True
    if result in ("float", "integer"):
        return kind == NUMBER
    if result == "date":
        return kind in (DATE, DATETIME)
    if result == "datetime":
        return kind in (DATE, DATETIME)
    return kind == BOOL


# -- working it out ---------------------------------------------------------


def _shown(v: Any) -> str:
    if isinstance(v, bool):
        return "yes/no"
    if isinstance(v, (int, float)):
        return "a number"
    if isinstance(v, str):
        return "text"
    if isinstance(v, (date, datetime)):
        return "a date"
    if isinstance(v, list):
        return "a list"
    return "a value"


def _from_field(value: Any, dtype: str) -> Any:
    """A stored value as a formula reads it."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, list) and not value:
        return None
    if dtype == "date" and isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            return value  # a year or month: year()/month() still read it
    if dtype == "datetime" and isinstance(value, str):
        try:
            moment = datetime.fromisoformat(value)
        except ValueError:
            return value
        return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)
    return value


def _evaluate(node: ast.expr, values: dict[str, Any]) -> Any:
    name = _name_of(node)
    if name is not None:
        return values.get(name)
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.UnaryOp):
        v = _evaluate(node.operand, values)
        if v is None:
            return None
        if isinstance(node.op, ast.Not):
            return not v
        n = _num(v, "-")
        return -n if isinstance(node.op, ast.USub) else n
    if isinstance(node, ast.BoolOp):
        found: list[Any] = []
        for part in node.values:
            v = _evaluate(part, values)
            if v is None:
                return None
            found.append(v)
            # Short-circuit like and/or read.
            if isinstance(node.op, ast.And) and not v:
                return False
            if isinstance(node.op, ast.Or) and v:
                return True
        return isinstance(node.op, ast.And)
    if isinstance(node, ast.Compare):
        left = _evaluate(node.left, values)
        for op, right_node in zip(node.ops, node.comparators):
            right = _evaluate(right_node, values)
            if left is None or right is None:
                return None
            try:
                ok = _CMPOPS[type(op)](left, right)
            except TypeError:
                raise FormulaError(
                    f"can't compare {_shown(left)} with {_shown(right)}"
                ) from None
            if not ok:
                return False
            left = right
        return True
    if isinstance(node, ast.IfExp):
        test = _evaluate(node.test, values)
        if test is None:
            return None
        return _evaluate(node.body if test else node.orelse, values)
    if isinstance(node, ast.BinOp):
        a = _evaluate(node.left, values)
        b = _evaluate(node.right, values)
        if a is None or b is None:
            return None
        return _binop(_BINOPS[type(node.op)], a, b)
    if isinstance(node, ast.Call):
        assert isinstance(node.func, ast.Name)
        fname = node.func.id
        args = [_evaluate(a, values) for a in node.args]
        if fname != "coalesce" and any(a is None for a in args):
            return None
        return FUNCTIONS[fname].call(*args)
    raise FormulaError("can't work that out")


def _binop(op: str, a: Any, b: Any) -> Any:
    if op == "+" and isinstance(a, str) and isinstance(b, str):
        return _capped(a + b)
    a, b = _num(a, op), _num(b, op)
    try:
        if op == "+":
            return a + b
        if op == "-":
            return a - b
        if op == "*":
            return a * b
        if op == "/":
            return a / b
        if op == "//":
            return a // b
        if op == "%":
            return a % b
        if abs(b) > MAX_EXPONENT:
            raise FormulaError(f"a power can be at most {MAX_EXPONENT}")
        result = float(a) ** float(b)
        if isinstance(result, complex):
            raise FormulaError("a negative number to a fractional power")
        return result
    except ZeroDivisionError:
        raise FormulaError("divided by zero") from None
    except OverflowError:
        raise FormulaError("the number is too large") from None


def _to_result(value: Any, result: str, decimals: int | None) -> Any:
    """`value` as a field of type `result` holds it."""
    if value is None:
        return None
    if result in ("float", "integer"):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise FormulaError(f"the result is {_shown(value)}, not a number")
        n = value
        if isinstance(n, float) and not math.isfinite(n):
            raise FormulaError("the result is not a finite number")
        if result == "integer":
            return int(round(n))
        return round(float(n), decimals) if decimals is not None else float(n)
    if result == "string":
        return _capped(_text(value))
    if result == "boolean":
        if not isinstance(value, bool):
            raise FormulaError(f"the result is {_shown(value)}, not yes/no")
        return value
    if result == "date":
        if isinstance(value, datetime):
            return value.date().isoformat()
        if isinstance(value, date):
            return value.isoformat()
        raise FormulaError(f"the result is {_shown(value)}, not a date")
    if result == "datetime":
        moment = _as_moment(value, "the result")
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        return moment.astimezone(timezone.utc).isoformat()
    raise FormulaError(f"unknown result type {result!r}")


def compute(
    formula: Formula,
    values: dict[str, Any],
    dtypes: dict[str, str],
    result: str,
    decimals: int | None = None,
) -> tuple[Any, str | None]:
    """`formula` worked out over a record's `values` (stored form, by name;
    `dtypes` says each one's field type, a formula's being its result type):
    `(value, None)`, or `(None, why)` when it can't be. Never raises for a
    value: one record's problem must not stop a list."""
    readable = {n: _from_field(values.get(n), dtypes.get(n, "")) for n in formula.names}
    try:
        return _to_result(_evaluate(formula.tree, readable), result, decimals), None
    except FormulaError as e:
        return None, str(e)
    except (ArithmeticError, ValueError, TypeError, RecursionError) as e:
        return None, f"can't be worked out ({type(e).__name__})"


# -- names --------------------------------------------------------------------


def uses(formula: Formula, name: str, via: str | None = None) -> bool:
    """Whether `formula` reads the field `name` directly (`via` None: `name`
    or `name.x`), or through the link field `via` (`via.name`)."""
    for n in formula.names:
        base, _, sub = n.partition(".")
        if via is None and base == name:
            return True
        if via is not None and base == via and sub == name:
            return True
    return False


def rename(source: str, old: str, new: str, via: str | None = None) -> str:
    """`source` with the field `old` called `new` wherever it is read (`via`
    as in `uses`); everything else, spacing included, is kept."""
    formula = parse(source)
    text = formula.source
    lines = text.split("\n")
    # (line, start byte, end byte) of each name to replace.
    spans: list[tuple[int, int, int]] = []
    for node in ast.walk(formula.tree):
        if via is None and isinstance(node, ast.Name) and node.id == old:
            assert node.end_col_offset is not None
            spans.append((node.lineno, node.col_offset, node.end_col_offset))
        if (
            via is not None
            and isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == via
            and node.attr == old
        ):
            assert node.end_col_offset is not None and node.end_lineno is not None
            end = node.end_col_offset
            spans.append((node.end_lineno, end - len(old.encode()), end))
    if not spans:
        return text
    encoded = [line.encode() for line in lines]
    for lineno, start, end in sorted(spans, reverse=True):
        line = encoded[lineno - 1]
        encoded[lineno - 1] = line[:start] + new.encode() + line[end:]
    return "\n".join(line.decode() for line in encoded)


__all__ = [
    "FUNCTIONS",
    "KIND_OF_DTYPE",
    "KIND_OF_RESULT",
    "RESULT_OF_KIND",
    "RESULT_TYPES",
    "Formula",
    "FormulaError",
    "compute",
    "fits",
    "infer",
    "kind_words",
    "parse",
    "rename",
    "uses",
]
