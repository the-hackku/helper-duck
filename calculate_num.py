import math
import re
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from typing import Optional

_expr_executor = ThreadPoolExecutor(max_workers=2)
_EVAL_TIMEOUT = 5  # seconds

# Matches eval-at notation: \big|_{x=1} or \bigg|_{x=2} or just |_{x=1}
_EVAL_AT_RE = re.compile(
    r"^(.*?)\\big[gl]?\|_\{([^}]+)\}\s*$|^(.*?)\|_\{([^}]+)\}\s*$", re.DOTALL
)


def _parse_subs(subs_str: str):
    from sympy import sympify, symbols

    result = {}
    for part in subs_str.split(","):
        if "=" in part:
            var, val = part.split("=", 1)
            result[symbols(var.strip())] = sympify(val.strip())
    return result


def _evaluate_expr(msg: str) -> Optional[int]:
    from sympy import N, sympify
    from sympy.parsing.latex import parse_latex

    # Handle evaluation-at notation before passing to the parser
    subs = {}
    m = _EVAL_AT_RE.match(msg)
    if m:
        expr_str = (m.group(1) or m.group(3) or "").strip()
        subs_str = (m.group(2) or m.group(4) or "").strip()
        try:
            subs = _parse_subs(subs_str)
        except Exception:
            return None
    else:
        expr_str = msg

    expr = None
    try:
        expr = parse_latex(expr_str, strict=True)
    except Exception:
        pass

    if expr is None:
        try:
            expr = sympify(expr_str)
        except Exception:
            return None

    try:
        if subs:
            expr = expr.doit().subs(subs)
        result = float(N(expr))
    except Exception:
        return None

    if not math.isfinite(result) or result < 0:
        return None

    return int(result)


def convert_to_int(message: str) -> Optional[int]:
    future = _expr_executor.submit(_evaluate_expr, message.strip())
    try:
        return future.result(timeout=_EVAL_TIMEOUT)
    except (FuturesTimeout, Exception):
        future.cancel()
        return None
