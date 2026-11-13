"""YAML → 노드 트리. 블록 그림의 텍스트 형태를 그대로 읽는다.
모듈과 조건 블록의 갈림까지 미리 다 짓기 때문에, 모르는 블록·없는 입력은 로봇이 움직이기 전에 잡힌다."""
from __future__ import annotations

import re
from typing import Any

from ..core.blackboard import ProgramError
from ..core.registry import REQUIRED, MacroDef, Registry
from ..core.skill import Condition
from . import nodes as N

CONTROL = {"Sequence", "Parallel", "Loop", "If", "Gate", "Set"}
ENDS = ("continue", "stop", "again")


class Loader:
    def __init__(self, registry: Registry) -> None:
        self.registry = registry
        self._trees: dict[tuple[str, str], N.Node] = {}
        self._building: list[str] = []
        self._env: list[dict[str, Any]] = [{}]      # 짓는 중인 모듈에서 변수 이름 → 타입 이름 (또는 {칸: 타입})

    # ------------------------------------------------------------ 타입 (실행 전 검사)
    def _reftype(self, v: Any) -> str | None:
        """`$변수.칸` 하나만 적힌 값의 타입 이름. 숫자·글자를 직접 적었거나 계산식이면 None (검사하지 않는다)."""
        if not (isinstance(v, str) and re.fullmatch(r"\s*\$[\w.]+\s*", v)):
            return None
        head, *rest = v.strip()[1:].split(".")
        t = None if head == "params" else self._env[-1].get(head)
        for seg in rest:
            if isinstance(t, dict):
                t = t.get(seg)
            elif isinstance(t, str) and t in self.registry.types:
                t = self.registry.types[t].fields.get(seg)
            else:
                return None
        return t if isinstance(t, str) else None

    def _check_slot(self, id: str, block: str, slot: str, want: str | None, given: Any) -> None:
        got = self._reftype(given)
        if want and got and got != want:
            raise ProgramError(f"{id}: {block} 의 칸 {slot} 은 {want} 인데, 꽂은 {str(given).strip()} 는 {got} 이다")

    def _remember(self, out: str | None, t: Any) -> None:
        if out and "." not in out:
            if t:
                self._env[-1][out] = t
            else:
                self._env[-1].pop(out, None)

    def _known(self, names: list, where: str) -> None:
        bad = [t for t in names if t not in self.registry.types]
        if bad:
            raise ProgramError(f"{where}: 모르는 타입 {bad} (있는 것: {sorted(self.registry.types)})")

    # 모듈은 부르는 자리마다 따로 짓는다 (노드 id = 부른 자리 경로 → 이벤트·하이라이트가 자리별로 구분된다)
    def tree(self, mdef: MacroDef, at: str = "") -> N.Node:
        key = (mdef.name, at)
        if key not in self._trees:
            if mdef.name in self._building:
                raise ProgramError(f"모듈 {mdef.name} 이 자기 자신을 부른다 ({' → '.join(self._building)})")
            self._known(list(mdef.types.values()), f"모듈 {mdef.name} 의 입력 칸")
            outs = mdef.out_types if isinstance(mdef.out_types, dict) else {"": mdef.out_types} if mdef.out_types else {}
            self._known(list(outs.values()), f"모듈 {mdef.name} 의 출력 칸")
            self._building.append(mdef.name)
            self._env.append(dict(mdef.types))
            try:
                self._trees[key] = self.build(mdef.main, f"{at}/{mdef.name}" if at else mdef.name)
                vals = mdef.returns if isinstance(mdef.returns, dict) else {"": mdef.returns}
                for slot, want in outs.items():
                    self._check_slot(mdef.name, f"모듈 {mdef.name}", f"출력 {slot}".strip(), want, vals[slot])
            finally:
                self._env.pop()
                self._building.pop()
        return self._trees[key]

    def abort_tree(self, mdef: MacroDef) -> N.Node | None:
        if mdef.on_abort is None:
            return None
        self._env.append(dict(mdef.types))
        try:
            return self.build(mdef.on_abort, f"{mdef.name}:on_abort")
        finally:
            self._env.pop()

    # ------------------------------------------------------------ 한 항목
    def build(self, item: Any, prefix: str) -> N.Node:
        if isinstance(item, str):
            item = {item: {}}
        if not (isinstance(item, dict) and len(item) == 1):
            raise ProgramError(f"{prefix}: 블록은 `이름: {{입력}}` 하나여야 한다 — {item!r}")
        (name, args), = item.items()
        id = f"{prefix}.{name}"
        if name in CONTROL:
            return getattr(self, f"_{name.lower()}")(id, args)
        if name in self.registry.macros:
            args = dict(args or {})
            out = self._var(args.pop("out", None))
            guards = self._guards(args.pop("guards", None), id)
            mdef = self.registry.macros[name]
            unknown = set(args) - set(mdef.inputs)
            missing = [k for k, d in mdef.inputs.items() if d is REQUIRED and k not in args]
            if unknown or missing:
                raise ProgramError(f"{id}: 모듈 {name} 의 입력 칸이 안 맞는다 — 없는 칸 {sorted(unknown)}, 빠진 칸 {missing} "
                                   f"(칸: {mdef.types})")
            for slot, given in args.items():
                self._check_slot(id, name, slot, mdef.types[slot], given)
            node = N.MacroNode(id, name, args, guards, out, self)
            self.tree(self.registry.macros[name], id)          # 미리 지어 본다
            self._remember(out, mdef.out_types)
            return node
        cls = self.registry.skills.get(name)
        if cls is None:
            raise ProgramError(f"{prefix}: 모르는 블록 {name}")
        if issubclass(cls, Condition):
            raise ProgramError(f"{id}: 조건은 If 의 check 나 조건 블록 정의에만 들어간다")
        return self._action(id, name, dict(args or {}))

    def seq(self, body: list, id: str) -> N.Sequence:
        return N.Sequence(id, [self.build(c, f"{id}[{i}]") for i, c in enumerate(body)])

    def branch(self, spec: Any, id: str, why: str) -> N.Branch:
        """갈림: 없음 = 본류 계속 / `continue` / `stop` / `again` / [블록 …, 끝]. 목록에 끝을 안 적으면 멈춤."""
        if spec is None:
            return N.Branch(None, "continue", why)
        if isinstance(spec, str):
            if spec not in ENDS:
                raise ProgramError(f"{id}: 갈림은 {' / '.join(ENDS)} 또는 블록 목록 — {spec!r}")
            return N.Branch(None, spec, why)
        if not isinstance(spec, list):
            raise ProgramError(f"{id}: 갈림은 {' / '.join(ENDS)} 또는 블록 목록 — {spec!r}")
        body, end = list(spec), "stop"
        if body and isinstance(body[-1], str) and body[-1] in ENDS:
            end = body.pop()
        return N.Branch(self.seq(body, id) if body else None, end, why)

    @staticmethod
    def _var(v: Any) -> str | None:
        return None if v is None else str(v).lstrip("$")

    def _conds(self, spec: Any, id: str) -> list[N.CondSpec]:
        items = spec if isinstance(spec, list) else [spec]
        out = []
        for it in items:
            if isinstance(it, str):
                it = {it: {}}
            (name, args), = it.items()
            cls = self.registry.skills.get(name)
            if cls is None or not issubclass(cls, Condition):
                raise ProgramError(f"{id}: {name} 은 조건이 아니다")
            out.append(N.CondSpec(name, dict(args or {})))
        return out

    def _guards(self, spec: Any, id: str) -> list[N.GuardSpec]:
        """`guards: [이름, {이름: {값}}]` — 이름은 조건 블록. 값은 조건 블록에 적힌 값 위에 덮는다."""
        out = []
        for g in spec or []:
            if isinstance(g, str):
                g = {g: {}}
            if not (isinstance(g, dict) and len(g) == 1):
                raise ProgramError(f"{id}: 가드는 조건 블록 이름 또는 `{{이름: {{값}}}}` — {g!r}")
            (name, extra), = g.items()
            cdef = self.registry.conditions.get(name)
            if cdef is None:
                raise ProgramError(f"{id}: 모르는 조건 블록 {name} (있는 것: {sorted(self.registry.conditions)})")
            cls = self.registry.skills.get(cdef.check)
            if cls is None or not issubclass(cls, Condition):
                raise ProgramError(f"조건 블록 {name}: {cdef.check} 은 조건이 아니다")
            args = {**cdef.args, **(extra or {})}
            unknown = set(args) - set(cls.Input.model_fields)
            if unknown:
                raise ProgramError(f"{id}: 조건 블록 {name} 에 없는 값 {sorted(unknown)} (있는 것: {list(cls.Input.model_fields)})")
            out.append(N.GuardSpec(name, cdef.check, args, self.branch(cdef.then, f"{id}.when:{name}", name)))
        return out

    # ------------------------------------------------------------ 제어 노드
    def _sequence(self, id: str, args: Any) -> N.Node:
        return self.seq(args or [], id)

    def _parallel(self, id: str, args: Any) -> N.Node:
        kids, policy = (args, "all") if isinstance(args, list) else (args["children"], args.get("policy", "all"))
        return N.Parallel(id, policy, [self.build(c, f"{id}[{i}]") for i, c in enumerate(kids)])

    def _loop(self, id: str, args: Any) -> N.Node:
        body, n = (args, None) if isinstance(args, list) else (args["body"], args.get("n"))
        return N.Loop(id, self.seq(body, f"{id}.body"), n)

    def _if(self, id: str, args: dict) -> N.Node:
        if ("expr" in args) == ("check" in args):
            raise ProgramError(f"{id}: If 는 expr 또는 check 중 하나")
        why = str(args.get("expr") or args.get("check"))
        check = self._conds(args["check"], id) if "check" in args else []
        return N.If(id, args.get("expr"), check, self.branch(args.get("then"), f"{id}.then", why),
                    self.branch(args.get("else"), f"{id}.else", f"not ({why})"))

    def _gate(self, id: str, args: dict) -> N.Node:
        spec = args.get("choices") or {"continue": "continue", "stop": "stop"}
        choices = {str(k): self.branch(v, f"{id}.{k}", f"operator: {k}") for k, v in spec.items()}
        self._remember(self._var(args.get("out")), "Decision")
        return N.Gate(id, args.get("prompt", ""), choices, args.get("autonomy", "high"), self._var(args.get("out")))

    def _set(self, id: str, args: dict) -> N.Node:
        for k, v in args.items():                    # 변수를 그대로 옮기면 타입도 따라간다. 계산식이면 모른다
            self._remember(str(k).lstrip("$"), self._reftype(v))
        return N.Set(id, dict(args))

    # ------------------------------------------------------------ 동작 블록
    def _action(self, id: str, name: str, args: dict) -> N.Node:
        cls = self.registry.skills[name]
        guards = self._guards(args.pop("guards", None), id)
        out = self._var(args.pop("out", None))
        unknown = set(args) - set(cls.Input.model_fields)
        if unknown:
            raise ProgramError(f"{id}: {name} 에 없는 입력 {sorted(unknown)} (있는 것: {list(cls.Input.model_fields)})")
        for slot, given in args.items():
            self._check_slot(id, name, slot, cls.slots.get(slot), given)
        self._remember(out, cls.gives)
        return N.ActionNode(id, name, args, guards, out)
