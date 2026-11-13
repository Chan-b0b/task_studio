"""레지스트리: 이름 → 스킬 클래스 / 매크로(YAML 파일). 두 층이 여기에 자기 블록을 등록한다."""
from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .blackboard import ProgramError
from .skill import Skill
from .typedefs import TypeDef, check_catalog, load_types

REQUIRED = object()


@dataclass
class MacroDef:
    name: str
    inputs: dict[str, Any]            # 이름 → 기본값 (REQUIRED = 꼭 줘야 함)
    main: Any
    types: dict[str, str] = field(default_factory=dict)   # 입력 칸 이름 → 타입 이름
    returns: Any = None               # outputs 의 값: None / "$변수"(값 하나) / {칸: 값}
    out_types: Any = None             # outputs 의 타입: None / "타입"(값 하나) / {칸: 타입}
    on_abort: Any = None
    path: str = ""
    layer: str = "base"
    tree: Any = field(default=None, repr=False)
    abort_tree: Any = field(default=None, repr=False)


@dataclass
class CondDef:
    """조건 블록: 조건 + 걸리면 할 일 + 끝. 한 번 적고 동작·모듈에 이름으로 꽂는다."""
    name: str
    check: str                        # 조건 스킬 이름 (ForceOver …)
    args: dict
    then: Any = None                  # None = 멈춤 / "continue" / [블록 …, 끝]


class Registry:
    def __init__(self) -> None:
        self.skills: dict[str, type[Skill]] = {}
        self.macros: dict[str, MacroDef] = {}
        self.conditions: dict[str, CondDef] = {}
        self.types: dict[str, TypeDef] = {}   # 칸에 적는 타입 이름 → 정의 (types.yaml)

    def add_types_file(self, path: str | Path, layer: str = "base", py: dict[str, Any] | None = None) -> None:
        self.types.update(load_types(path, layer, py))
        check_catalog(self.types)

    def check_skills(self) -> None:
        """파이썬 블록의 칸 선언(slots / gives)이 Input 필드·타입 목록과 맞는지."""
        for name, cls in self.skills.items():
            fields = set(cls.Input.model_fields)
            if set(cls.slots) != fields:
                raise ProgramError(f"블록 {name}: slots 가 Input 과 다르다 — 빠진 칸 {sorted(fields - set(cls.slots))}, 없는 칸 {sorted(set(cls.slots) - fields)}")
            for t in list(cls.slots.values()) + ([cls.gives] if cls.gives else []):
                if t not in self.types:
                    raise ProgramError(f"블록 {name}: 모르는 타입 {t}")

    def add_conditions(self, spec: dict, where: str = "") -> None:
        for name, d in (spec or {}).items():
            check = (d or {}).get("check")
            if isinstance(check, str):
                check = {check: {}}
            if not (isinstance(check, dict) and len(check) == 1):
                raise ProgramError(f"{where}: 조건 블록 {name} 은 `check: {{조건: {{값}}}}` 하나가 있어야 한다")
            (cname, args), = check.items()
            self.conditions[str(name)] = CondDef(str(name), cname, dict(args or {}), d.get("then", "stop") if "then" in d else "stop")

    def add_conditions_file(self, path: str | Path) -> None:
        self.add_conditions(yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}, str(path))

    def add(self, cls: type[Skill]) -> type[Skill]:
        self.skills[cls.name] = cls
        return cls

    def add_module(self, module: Any, layer: str | None = None) -> None:
        for _, obj in inspect.getmembers(module, inspect.isclass):
            if issubclass(obj, Skill) and obj.__module__ == module.__name__ and "name" in vars(obj):
                if layer:
                    obj.layer = layer
                self.add(obj)

    def add_yaml(self, path: str | Path, layer: str = "base") -> MacroDef:
        path = Path(path)
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if "main" not in doc:
            raise ProgramError(f"{path}: main 이 없다")
        inputs: dict[str, Any] = {}
        types: dict[str, str] = {}
        raw = doc.get("inputs")
        if not isinstance(raw, dict):
            raise ProgramError(f"{path}: inputs 는 `{{이름: 타입}}` 으로 적는다 (받는 것이 없으면 `inputs: {{}}`)")
        for name, spec in raw.items():
            if isinstance(spec, dict):            # {type: number, default: 0.0}
                if "type" not in spec:
                    raise ProgramError(f"{path}: 입력 칸 {name} 에 type 이 없다")
                types[name], inputs[name] = str(spec["type"]), spec["default"] if "default" in spec else REQUIRED
            else:
                types[name], inputs[name] = str(spec), REQUIRED
        self.add_conditions(doc.get("conditions"), str(path))
        returns, out_types = self._outputs(doc.get("outputs"), path)
        m = MacroDef(name=doc.get("name", path.stem), inputs=inputs, types=types, main=doc["main"],
                     returns=returns, out_types=out_types, on_abort=doc.get("on_abort"), path=str(path), layer=layer)
        self.macros[m.name] = m
        return m

    @staticmethod
    def _outputs(raw: Any, path: Path) -> tuple[Any, Any]:
        """outputs: 없음 / {type, value}(값 하나) / {칸: {type, value}}. 출력에도 타입을 반드시 적는다."""
        def one(spec: Any, what: str) -> tuple[Any, str]:
            if not (isinstance(spec, dict) and set(spec) == {"type", "value"}):
                raise ProgramError(f"{path}: {what} 은 `{{type: 타입, value: 값}}` 으로 적는다 — {spec!r}")
            return spec["value"], str(spec["type"])
        if raw is None:
            return None, None
        if isinstance(raw, dict) and set(raw) == {"type", "value"}:
            return one(raw, "outputs")
        if not isinstance(raw, dict):
            raise ProgramError(f"{path}: outputs 는 `{{type, value}}` 하나 또는 `{{칸: {{type, value}}}}` — {raw!r}")
        pairs = {str(k): one(v, f"출력 칸 {k}") for k, v in raw.items()}
        return {k: v for k, (v, _) in pairs.items()}, {k: t for k, (_, t) in pairs.items()}

    def add_yaml_dir(self, folder: str | Path, layer: str = "base") -> None:
        for p in sorted(Path(folder).glob("*.yaml")):
            self.add_yaml(p, layer)

    def catalog(self) -> list[dict]:
        """블록 목록 (편집기 툴박스·문서용): 종류 | 층 | 파트 | 이름 | 입력."""
        rows = []
        for name, cls in sorted(self.skills.items()):
            rows.append({"name": name, "kind": cls.kind, "layer": cls.layer, "part": cls.part,
                         "inputs": dict(cls.slots), "gives": cls.gives})
        for name, m in sorted(self.macros.items()):
            rows.append({"name": name, "kind": "macro", "layer": m.layer, "part": "", "inputs": dict(m.types), "gives": m.out_types})
        return rows
