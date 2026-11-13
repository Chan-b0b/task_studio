"""실행기: 프로그램 하나를 처음부터 끝까지. 중단되면 on_abort 트리를 돌린다. 스레드 하나, 스킬은 블로킹."""
from __future__ import annotations

import threading
from typing import Any

from ..core.blackboard import Blackboard, ProgramError
from ..core.context import Context, EventLog, RealClock, Resources, ScriptedOperator
from ..core.registry import Registry
from ..core.skill import Aborted, Again, Result, Stopped
from .loader import Loader
from .nodes import NodeResult, bind_inputs, macro_output


class Executor:
    def __init__(self, registry: Registry, robot: Any, params: dict, operator: Any = None,
                 events: EventLog | None = None, clock: Any = None, store: dict | None = None) -> None:
        self.registry, self.robot, self.params = registry, robot, params
        self.clock = clock or RealClock()
        self.operator = operator or ScriptedOperator()
        self.events = events or EventLog(clock=self.clock)
        self.store = store if store is not None else {}
        self.loader = Loader(registry)
        self.stop = threading.Event()
        self.scope: Blackboard | None = None      # 끝난 뒤 변수 들여다보기용

    def request_stop(self) -> None:
        self.stop.set()

    def run(self, program: str, inputs: dict | None = None) -> Result:
        mdef = self.registry.macros.get(program)
        if mdef is None:
            raise ProgramError(f"모르는 프로그램 {program}")
        shared = Blackboard({"params": self.params})
        scope = self.scope = shared.child()
        ctx = Context(robot=self.robot, bb=scope, registry=self.registry, events=self.events, operator=self.operator,
                      clock=self.clock, stop=self.stop, resources=Resources(), store=self.store,
                      dt=float(self.params.get("tick_s", 0.01)))
        ctx.emit("run_start", program=program, robot=type(self.robot).__name__, inputs=inputs or {})
        r, error = NodeResult(), None
        try:
            bind_inputs(mdef, inputs or {}, None, scope, self.registry.types)
            tree = self.loader.tree(mdef)          # 여기서 모듈·조건 블록까지 다 짓는다 → 틀린 곳은 움직이기 전에 잡힌다
            self.loader.abort_tree(mdef)
            tree.execute(ctx)
        except Stopped as e:
            r = NodeResult("stopped", str(e))
        except Again:
            r, error = NodeResult("aborted", "program_error: again 은 Loop 상자 안에서만 쓴다"), ProgramError("again 은 Loop 상자 안에서만 쓴다")
        except Aborted as e:
            r = NodeResult("aborted", str(e))
        except ProgramError as e:
            r, error = NodeResult("aborted", f"program_error: {e}"), e
            ctx.emit("error", message=str(e))
        if r.status == "aborted":
            self._recover(mdef, ctx)
        ctx.emit("run_end", status=r.status, reason=r.reason)
        if error is not None and self.params.get("raise_program_errors", False):
            raise error
        return Result(status=r.status, reason=r.reason)

    def _recover(self, mdef, ctx: Context) -> None:
        """어디서 멈췄든 on_abort 트리를 돈다. 정지 요청은 여기서 푼다(복구 동작이 움직여야 하므로)."""
        self.stop.clear()
        ctx = ctx.derive(resources=Resources(), guards=(), cancels=())
        try:
            tree = self.loader.abort_tree(mdef)
            if tree is None:
                return
            ctx.emit("abort_recovery", program=mdef.name)
            tree.execute(ctx)
        except (Aborted, ProgramError) as e:
            ctx.emit("error", message=f"on_abort 도 끝까지 못 감: {e}")
