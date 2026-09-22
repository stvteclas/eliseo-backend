"""Calculadora segura y conversión de monedas (Frankfurter, sin API key)."""

from __future__ import annotations

import ast
import operator
import re

import httpx

_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
    ast.Mod: operator.mod,
}


def _eval_node(node: ast.AST) -> float:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return float(node.value)
    if isinstance(node, ast.BinOp):
        op = _OPS.get(type(node.op))
        if op is None:
            raise ValueError("Operación no permitida")
        return float(op(_eval_node(node.left), _eval_node(node.right)))
    if isinstance(node, ast.UnaryOp):
        op = _OPS.get(type(node.op))
        if op is None:
            raise ValueError("Operación no permitida")
        return float(op(_eval_node(node.operand)))
    if isinstance(node, ast.Expr):
        return _eval_node(node.value)
    raise ValueError("Expresión no permitida")


def evaluate_expression(expression: str) -> str:
    """
    Evalúa una expresión aritmética simple (+ - * / ** % y paréntesis).
    También acepta '15% de 2400' → 0.15 * 2400.
    """
    raw = (expression or "").strip()
    if not raw:
        return "Decime la cuenta que querés hacer."

    percent = re.match(
        r"^\s*(\d+(?:[.,]\d+)?)\s*%\s*(?:de|of)?\s*(\d+(?:[.,]\d+)?)\s*$",
        raw,
        flags=re.IGNORECASE,
    )
    if percent:
        a = float(percent.group(1).replace(",", "."))
        b = float(percent.group(2).replace(",", "."))
        result = a / 100.0 * b
        return f"{a}% de {b} es {result:g}."

    cleaned = raw.replace(",", ".").replace("×", "*").replace("÷", "/")
    cleaned = re.sub(r"[^0-9+\-*/().%\s]", "", cleaned)
    cleaned = cleaned.replace("%", "/100")
    try:
        tree = ast.parse(cleaned, mode="eval")
        result = _eval_node(tree.body)
    except Exception:
        return "No pude calcular esa expresión. Probá algo como 15*160 o 15% de 2400."
    if not (result == result) or abs(result) == float("inf"):  # NaN / inf
        return "El resultado no es un número válido."
    return f"El resultado es {result:g}."


def convert_currency(amount: float, from_currency: str, to_currency: str) -> str:
    """Convierte monedas con tasas del día (Frankfurter / BCE)."""
    src = (from_currency or "").strip().upper()
    dst = (to_currency or "").strip().upper()
    if not src or not dst:
        return "Necesito las monedas de origen y destino (ej. USD y ARS)."
    # Frankfurter no cotiza ARS; usamos open.er-api.com como fallback general.
    try:
        with httpx.Client() as client:
            response = client.get(f"https://open.er-api.com/v6/latest/{src}", timeout=15)
            response.raise_for_status()
            data = response.json()
        if data.get("result") != "success":
            return "No pude obtener el tipo de cambio ahora."
        rates = data.get("rates") or {}
        if dst not in rates:
            return f"No tengo cotización de {src} a {dst}."
        rate = float(rates[dst])
        converted = float(amount) * rate
        return f"{amount:g} {src} equivalen a {converted:.2f} {dst} (tasa aprox. {rate:g})."
    except httpx.HTTPError:
        return "No pude consultar el tipo de cambio en este momento."
    except (TypeError, ValueError):
        return "Monto o monedas inválidas."
