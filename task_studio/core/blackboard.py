"""블랙보드: `$이름` 변수가 사는 곳. 프로그램·매크로마다 자기 범위를 갖고, `params` 만 공유한다."""
from __future__ import annotations

import ast
import re
from typing import Any

from pydantic import BaseModel


class Unset(Exception):
    def __init__(self, path: str):
        super().__init__(f"${path} 에 값이 없다")
        self.path = path


class ProgramError(Exception):
    """프로그램(YAML)이 잘못 적혔다: 모르는 블록, 타입 안 맞는 입력, 파트 충돌 …"""


def _step(obj: Any, key: str, path: str) -> Any:
    try:
        if isinstance(obj, dict):
            return obj[key]
        if isinstance(obj, (list, tuple)):
            return obj[int(key)]
        if isinstance(obj, BaseModel):
            return getattr(obj, key)
    except (KeyError, IndexError, AttributeError, ValueError):
        pass
    raise Unset(path)


class Blackboard:
    def __init__(self, data: dict | None = None, shared: "Blackboard | None" = None):
        self.data: dict[str, Any] = dict(data or {})
        self.shared = shared                      # params 등 모든 범위가 같이 보는 값

    def child(self, data: dict | None = None) -> "Blackboard":
        return Blackboard(data, shared=self.shared or self)

    def has(self, name: str) -> bool:
        return name in self.data or (self.shared is not None and name in self.shared.data)

    def get(self, path: str) -> Any:
        root, *rest = path.split(".")
        if root in self.data:
            obj = self.data[root]
        elif self.shared is not None and root in self.shared.data:
            obj = self.shared.data[root]
        else:
            raise Unset(path)
        for key in rest:
            obj = _step(obj, key, path)
        return obj

    def set(self, path: str, value: Any) -> None:
        *prefix, last = path.split(".")
        if not prefix:
            self.data[last] = value
            return
        obj = self.get(".".join(prefix))
        if isinstance(obj, dict):
            obj[last] = value
        elif isinstance(obj, BaseModel):
            setattr(obj, last, value)
        else:
            raise ProgramError(f"${path}: {type(obj).__name__} 안에는 값을 넣을 수 없다")


# ---------- 식: 산술·비교·논리만 ----------
_VAR = re.compile(r"\$([A-Za-z_]\w*(?:\.\w+)*)")
_ALLOWED = (
    ast.Expression, ast.BoolOp, ast.And, ast.Or, ast.UnaryOp, ast.Not, ast.USub, ast.UAdd,
    ast.BinOp, ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod,
    ast.Compare, ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.In, ast.NotIn, ast.Is, ast.IsNot,
    ast.Constant, ast.List, ast.Tuple, ast.IfExp, ast.Load, ast.Call, ast.Name,
)


def is_ref(text: str) -> bool:
    return bool(_VAR.fullmatch(text.strip()))


def evaluate(text: str, bb: Blackboard) -> Any:
    code = _VAR.sub(lambda m: f"__v({m.group(1)!r})", str(text))
    try:
        tree = ast.parse(code.strip(), mode="eval")
    except SyntaxError as e:
        raise ProgramError(f"식을 읽을 수 없다: {text!r} ({e.msg})") from None
    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED):
            raise ProgramError(f"식에 쓸 수 없는 것: {type(node).__name__} in {text!r}")
        if isinstance(node, ast.Name) and node.id != "__v":
            raise ProgramError(f"식에 모르는 이름: {node.id} in {text!r}")
        if isinstance(node, ast.Call) and not (isinstance(node.func, ast.Name) and node.func.id == "__v"):
            raise ProgramError(f"식에서는 함수를 부를 수 없다: {text!r}")
    return eval(compile(tree, "<expr>", "eval"), {"__builtins__": {}, "__v": bb.get})


def resolve(value: Any, bb: Blackboard) -> Any:
    """블록 입력 하나를 실제 값으로: `$변수` → 그 값, `$` 가 든 문자열 → 식, 나머지는 그대로."""
    if isinstance(value, str):
        if is_ref(value):
            return bb.get(value.strip()[1:])
        if "$" in value:
            return evaluate(value, bb)
        return value
    if isinstance(value, dict):
        return {k: resolve(v, bb) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve(v, bb) for v in value]
    return value
