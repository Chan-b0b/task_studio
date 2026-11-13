"""제어 노드 6개(Sequence, Parallel, Loop, If, Gate, Set) + 블록 노드(동작, 모듈).

갈림 규칙 (본류 = Sequence):
  본류를 벗어나는 곳은 셋 — 가드(조건 블록), If, Gate.
  갈림의 끝은 둘 — `continue` 본류 계속(가지에 블록이 있으면 하고 간다) / 안 적으면 멈춤(프로그램이 그 자리에서 끝난다).
  `again` 은 Loop 상자의 처음으로 돌아간다.
  블록이 실패해도 프로그램이 멈춘다. 운영자 중단·E-stop(Aborted)만 on_abort 를 돈다.
"""
from __future__ import annotations

import copy
import threading
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ValidationError

from ..core.blackboard import ProgramError, Unset, evaluate, resolve
from ..core.context import Context, Guard
from ..core.registry import REQUIRED, MacroDef
from ..core.skill import Aborted, Action, Again, Cancelled, GuardFired, Result, Stopped, Value
from ..core.types import Decision


@dataclass
class NodeResult:
    status: str = "ok"
    reason: str = ""
    info: dict = field(default_factory=dict)


OK = NodeResult


class Node:
    def __init__(self, id: str) -> None:
        self.id = id

    def label(self) -> str:
        return type(self).__name__

    def kids(self, ctx: Context) -> list["Node"]:
        return []

    def parts(self, ctx: Context) -> frozenset[str]:
        """이 가지가 쓸 수 있는 파트 전부 (Parallel 이 시작 전에 겹치는지 본다)."""
        return frozenset().union(*(k.parts(ctx) for k in self.kids(ctx)))

    def run(self, ctx: Context) -> NodeResult:
        raise NotImplementedError

    def execute(self, ctx: Context) -> NodeResult:
        ctx.emit("node_enter", node=self.id, type=self.label())
        try:
            r = self.run(ctx)
        except Stopped as e:
            ctx.emit("node_exit", node=self.id, type=self.label(), status="stopped", reason=str(e))
            raise
        except Again:
            ctx.emit("node_exit", node=self.id, type=self.label(), status="again")
            raise
        except (Aborted, Cancelled):
            ctx.emit("node_exit", node=self.id, type=self.label(), status="aborted")
            raise
        ctx.emit("node_exit", node=self.id, type=self.label(), status=r.status, **r.info)
        return r


class Branch:
    """갈림 하나: 할 일(없을 수 있다) + 끝(continue / stop / again)."""

    def __init__(self, body: "Sequence | None", end: str, why: str) -> None:
        self.body, self.end, self.why = body, end, why

    def kids(self) -> list[Node]:
        return [self.body] if self.body is not None else []

    def run(self, ctx: Context) -> None:
        if self.body is not None:
            self.body.execute(ctx)
        if self.end == "stop":
            raise Stopped(self.why)
        if self.end == "again":
            raise Again()


# ---------------------------------------------------------------- 제어 노드
class Sequence(Node):
    def __init__(self, id: str, children: list[Node]) -> None:
        super().__init__(id)
        self.children = children

    def kids(self, ctx: Context) -> list[Node]:
        return self.children

    def run(self, ctx: Context) -> NodeResult:
        for c in self.children:
            c.execute(ctx)
        return OK()


class Parallel(Node):
    def __init__(self, id: str, policy: str, children: list[Node]) -> None:
        super().__init__(id)
        if policy not in ("all", "any"):
            raise ProgramError(f"{id}: Parallel policy 는 all / any")
        self.policy, self.children = policy, children

    def kids(self, ctx: Context) -> list[Node]:
        return self.children

    def run(self, ctx: Context) -> NodeResult:
        claimed: dict[str, str] = {}
        for c in self.children:
            for part in c.parts(ctx):
                if part in claimed:
                    raise ProgramError(f"파트 충돌: {self.id} 의 두 가지({claimed[part]}, {c.label()})가 {part} 를 같이 쓴다")
                claimed[part] = c.label()
        cancel = threading.Event()
        errors: list[BaseException] = []

        def work(child: Node) -> None:
            try:
                child.execute(ctx.derive(cancels=ctx.cancels + (cancel,)))
                if self.policy == "any":
                    cancel.set()
            except Cancelled:
                pass
            except BaseException as e:          # Stopped, Aborted, ProgramError → 주 스레드에서 다시 던진다
                errors.append(e)
                cancel.set()

        threads = [threading.Thread(target=work, args=(c,), daemon=True) for c in self.children]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        if errors:
            raise errors[0]
        return OK()


class Loop(Node):
    """상자 안을 n 번 돈다. n 이 없으면 한 번 돌고, 안에서 `again` 이 나오면 처음으로 돌아간다."""

    def __init__(self, id: str, body: Node, n: Any = None) -> None:
        super().__init__(id)
        self.body, self.n = body, n

    def kids(self, ctx: Context) -> list[Node]:
        return [self.body]

    def run(self, ctx: Context) -> NodeResult:
        cap = int(ctx.params.get("loop_max", 1000))
        n = None if self.n is None else int(resolve(self.n, ctx.bb))
        turns = 0
        while True:
            if turns >= cap:
                raise ProgramError(f"{self.id}: Loop 가 {cap} 번을 넘었다")
            turns += 1
            try:
                self.body.execute(ctx)
            except Again:
                continue
            if n is None or turns >= n:
                return OK(info={"turns": turns})


@dataclass
class CondSpec:
    name: str
    args: dict


def _check(specs: list[CondSpec], ctx: Context) -> bool:
    for s in specs:
        cls = ctx.registry.skills[s.name]
        inp = cls.Input(**resolve(s.args, ctx.bb))
        cond = cls()
        cond.arm(ctx, inp)
        if not cond.check(ctx, inp):
            return False
    return True


class If(Node):
    def __init__(self, id: str, expr: str | None, check: list[CondSpec], then: Branch, else_: Branch) -> None:
        super().__init__(id)
        self.expr, self.check, self.then, self.else_ = expr, check, then, else_

    def kids(self, ctx: Context) -> list[Node]:
        return self.then.kids() + self.else_.kids()

    def run(self, ctx: Context) -> NodeResult:
        try:
            truth = bool(evaluate(self.expr, ctx.bb)) if self.expr is not None else _check(self.check, ctx)
        except Unset as e:
            raise Stopped(f"unset ${e.path}") from None
        ctx.emit("branch", node=self.id, took="then" if truth else "else")
        (self.then if truth else self.else_).run(ctx)
        return OK(info={"took": "then" if truth else "else"})


class Gate(Node):
    """운영자가 고를 때까지 멈춘다. 선택지마다 갈림이 하나씩 있다."""

    def __init__(self, id: str, prompt: Any, choices: dict[str, Branch], autonomy: str, out: str | None) -> None:
        super().__init__(id)
        self.prompt, self.choices, self.autonomy, self.out = prompt, choices, autonomy, out

    def kids(self, ctx: Context) -> list[Node]:
        return [k for b in self.choices.values() for k in b.kids()]

    def run(self, ctx: Context) -> NodeResult:
        prompt, allowed = str(resolve(self.prompt, ctx.bb)), list(self.choices)
        if self.autonomy == "low" and ctx.params.get("autonomy") == "full":
            d = Decision(choice=allowed[0])
            ctx.emit("decision", node=self.id, choice=d.choice, args=d.args, auto=True)
        else:
            d = ctx.ask(prompt, allowed, node=self.id)
        if self.out:
            ctx.bb.set(self.out, d)
        self.choices[d.choice].run(ctx)
        return OK(info={"choice": d.choice})


class Set(Node):
    def __init__(self, id: str, assigns: dict[str, Any]) -> None:
        super().__init__(id)
        self.assigns = assigns

    def run(self, ctx: Context) -> NodeResult:
        try:
            for path, expr in self.assigns.items():
                value = evaluate(expr, ctx.bb) if isinstance(expr, str) else resolve(copy.deepcopy(expr), ctx.bb)
                ctx.bb.set(path.lstrip("$"), value)
        except Unset as e:
            raise Stopped(f"unset ${e.path}") from None
        return OK()


# ---------------------------------------------------------------- 블록 노드
@dataclass
class GuardSpec:
    """동작(또는 모듈)에 꽂힌 조건 블록 하나. name = 조건 블록 이름, check = 그 안의 조건, branch = 걸리면 할 일."""
    name: str
    check: str
    args: dict
    branch: Branch


def _arm_guards(specs: list[GuardSpec], ctx: Context) -> list[Guard]:
    out = []
    for g in specs:
        gcls = ctx.registry.skills[g.check]
        try:
            inp = gcls.Input(**resolve(g.args, ctx.bb))
        except ValidationError as e:
            raise ProgramError(f"조건 블록 {g.name}: {g.check} 입력이 맞지 않다 — {e.errors()[0]['loc']}: {e.errors()[0]['msg']}") from None
        out.append(Guard(g.name, gcls(), inp, g.branch))
    return out


class ActionNode(Node):
    """파이썬 블록 하나. 가드를 꽂고 돌린 뒤: 목표에 닿았으면 본류 계속, 가드에 걸렸으면 그 조건 블록의 갈림을 탄다."""

    def __init__(self, id: str, skill: str, inputs: dict, guards: list[GuardSpec], out: str | None) -> None:
        super().__init__(id)
        self.skill, self.inputs, self.guards, self.out = skill, inputs, guards, out

    def label(self) -> str:
        return self.skill

    def kids(self, ctx: Context) -> list[Node]:
        return [k for g in self.guards for k in g.branch.kids()]

    def parts(self, ctx: Context) -> frozenset[str]:
        cls = ctx.registry.skills[self.skill]
        try:
            own = cls.requires_for(cls.Input(**resolve(self.inputs, ctx.bb)))
        except (Unset, ValidationError):          # 아직 값이 없는 입력: 클래스에 적힌 것만
            own = cls.requires
        return own | super().parts(ctx)

    def run(self, ctx: Context) -> NodeResult:
        cls = ctx.registry.skills[self.skill]
        specs = list(self.guards)
        specs += [g for g in ctx.scope_guards if g.name not in {s.name for s in specs}]   # 모듈에 꽂힌 조건 블록은 안의 블록 전부에 걸린다
        try:
            raw = resolve(self.inputs, ctx.bb)
            guards = _arm_guards(specs, ctx)
        except Unset as e:
            raise Stopped(f"unset ${e.path}") from None
        try:
            inp = cls.Input(**raw)
        except ValidationError as e:
            raise ProgramError(f"{self.id}: {self.skill} 입력이 맞지 않다 — {e.errors()[0]['loc']}: {e.errors()[0]['msg']}") from None
        parts = cls.requires_for(inp)
        ctx.resources.acquire(parts, self.id)
        try:
            for g in guards:
                g.cond.arm(ctx, g.inp)
            inner = ctx.derive(guards=tuple(guards), at=self.id)
            try:
                res: Result | None = cls().run(inner, inp)
                stopped_by = getattr(res, "stopped_by", None)
            except GuardFired as e:               # 파이썬 블록이 안에서 부른 동작이 걸렸다 → 블록을 접는다
                res, stopped_by = None, e.name
        finally:
            ctx.resources.release(parts)
        if res is not None:
            if self.out:
                ctx.bb.set(self.out, res.value if isinstance(res, Value) else res)
            if res.status != "ok":
                ctx.emit("block_failed", node=self.id, reason=res.reason or stopped_by or "")
                raise Stopped(res.reason or stopped_by or self.skill)
            if not issubclass(cls, Action):       # 한 번에 끝나는 블록: 끝난 직후에 조건을 한 번 본다
                stopped_by = inner.poll() or stopped_by
        info = {"stopped_by": stopped_by} if stopped_by else {}
        g = next((g for g in guards if g.name == stopped_by), None)
        if g is not None:
            ctx.emit("guard", node=self.id, fired=stopped_by)
            g.then.run(ctx.derive(scope_guards=()))
        return OK(info=info)


def _typed(owner: str, what: str, tname: str, value: Any, types: dict) -> Any:
    """칸에 적힌 타입의 바탕(숫자 / 글자 / 목록 / 묶음)에 값이 맞는지 본다. 묶음은 dict 로 줘도 그 타입으로 바꿔 넣는다."""
    t = types.get(tname)
    if t is None:
        raise ProgramError(f"{owner}: {what} 의 타입 {tname} 을 모른다 (있는 것: {sorted(types)})")
    try:
        return t.check(value)
    except ValueError as e:
        raise ProgramError(f"{owner}: {what} — {e}") from None


def bind_inputs(mdef: MacroDef, given: dict | None, caller, scope, types: dict) -> None:
    """모듈 입력을 그 모듈의 범위에 넣는다. 모듈 안에서는 입력과 $params 만 보인다."""
    given = given or {}
    extra = set(given) - set(mdef.inputs)
    if extra:
        raise ProgramError(f"{mdef.name}: 모르는 입력 {sorted(extra)} (있는 것: {list(mdef.inputs)})")
    for name, default in mdef.inputs.items():
        if name in given:
            value = resolve(given[name], caller) if caller is not None else given[name]
        elif default is REQUIRED:
            raise ProgramError(f"{mdef.name}: 입력 {name} 이 없다")
        else:
            value = resolve(copy.deepcopy(default), scope)
        scope.set(name, _typed(mdef.name, f"입력 {name}", mdef.types[name], value, types))


def macro_output(mdef: MacroDef, scope, types: dict) -> Any:
    def one(v: Any, tname: str, what: str) -> Any:
        try:
            got = resolve(v, scope)
        except Unset:
            return None                      # 그 값을 만드는 블록까지 가지 못했다
        return None if got is None else _typed(mdef.name, what, tname, got, types)
    if mdef.returns is None:
        return Result()
    if not isinstance(mdef.returns, dict):
        return one(mdef.returns, mdef.out_types, "출력")
    return Result(**{k: one(v, mdef.out_types[k], f"출력 {k}") for k, v in mdef.returns.items()})


class MacroNode(Node):
    """모듈(다른 YAML 파일)을 블록처럼 부른다. 입력 칸으로 받고(`inputs`), 출력 칸으로 낸다(`outputs`).
    모듈 안에서는 입력과 `$params` 만 보인다."""

    def __init__(self, id: str, name: str, inputs: dict, guards: list[GuardSpec], out: str | None, loader: Any) -> None:
        super().__init__(id)
        self.name, self.inputs, self.guards, self.out, self.loader = name, inputs, guards, out, loader

    def label(self) -> str:
        return self.name

    def kids(self, ctx: Context) -> list[Node]:
        return [self.loader.tree(ctx.registry.macros[self.name], self.id)] + [k for g in self.guards for k in g.branch.kids()]

    def run(self, ctx: Context) -> NodeResult:
        mdef = ctx.registry.macros[self.name]
        scope = ctx.bb.child()
        try:
            bind_inputs(mdef, self.inputs, ctx.bb, scope, ctx.registry.types)
        except Unset as e:
            raise Stopped(f"unset ${e.path}") from None
        have = {g.name for g in self.guards}
        inner = ctx.derive(bb=scope, guards=(), scope_guards=tuple(self.guards) + tuple(g for g in ctx.scope_guards if g.name not in have))
        self.loader.tree(mdef, self.id).execute(inner)
        if self.out:
            ctx.bb.set(self.out, macro_output(mdef, scope, ctx.registry.types))
        return OK()
