"""칸에 적는 타입. 타입은 "값이 무엇인가"에 붙인 이름이다 (Height, Item, Pose …). 블록마다 결과 타입을 만들지 않는다.
`types.yaml` 한 줄이 타입 하나:
    Height: {base: number, unit: m, desc: 높이 z}
    Option: {base: text, choices: [top, side]}
    Detections: {base: list, of: ObjectPose}
    Stack:  {fields: {src: Count, tgt: Count}}            # 묶음
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ValidationError

from .blackboard import ProgramError

BASES = ("number", "text", "list", "bool", "struct")


@dataclass
class TypeDef:
    name: str
    base: str = "struct"                 # number / text / list / bool / struct
    unit: str = ""
    desc: str = ""
    choices: list = field(default_factory=list)
    of: str = ""                         # list 의 원소 타입
    fields: dict[str, str] = field(default_factory=dict)   # struct 의 칸 → 타입 이름
    py: Any = None                       # struct 를 담는 파이썬 클래스 (있으면 dict 를 이 클래스로 바꿔 넣는다)
    layer: str = "base"

    def check(self, value: Any) -> Any:
        """값이 이 타입의 바탕(base)에 맞는지 본다. 맞으면 값을(묶음은 클래스로 바꿔) 돌려주고, 아니면 ValueError."""
        b = self.base
        if b == "bool":
            ok = isinstance(value, bool)
        elif b == "number":
            ok = isinstance(value, (int, float)) and not isinstance(value, bool)
        elif b == "text":
            ok = isinstance(value, str)
            if ok and self.choices and value not in self.choices:
                raise ValueError(f"{self.name} 은 {self.choices} 중 하나여야 하는데 {value!r} 가 왔다")
        elif b == "list":
            ok = isinstance(value, (list, tuple))
        elif self.py is not None:
            if isinstance(value, self.py):
                return value
            if isinstance(value, dict):
                try:
                    return self.py.model_validate(value)
                except ValidationError:
                    pass
            ok = False
        else:
            ok = isinstance(value, (dict, BaseModel))
        if not ok:
            raise ValueError(f"{self.name}({self.base}) 이어야 하는데 {type(value).__name__} 이 왔다")
        return value


def load_types(path: str | Path, layer: str = "base", py: dict[str, Any] | None = None) -> dict[str, TypeDef]:
    out = {}
    for name, d in (yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}).items():
        d = dict(d or {})
        base = d.get("base", "struct")
        if base not in BASES:
            raise ProgramError(f"{path}: 타입 {name} 의 base 는 {BASES} 중 하나 — {base!r}")
        out[str(name)] = TypeDef(str(name), base, str(d.get("unit", "")), str(d.get("desc", "")), list(d.get("choices") or []),
                                 str(d.get("of", "")), {str(k): str(v) for k, v in (d.get("fields") or {}).items()},
                                 (py or {}).get(name), layer)
    return out


def check_catalog(types: dict[str, TypeDef]) -> None:
    """타입이 가리키는 타입(of, fields)이 전부 있는지."""
    for t in types.values():
        for ref in ([t.of] if t.of else []) + list(t.fields.values()):
            if ref not in types:
                raise ProgramError(f"타입 {t.name}: 모르는 타입 {ref}")
