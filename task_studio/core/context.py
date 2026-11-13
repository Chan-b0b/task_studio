"""Context: 스킬이 받는 것 전부 (로봇, 블랙보드, 기록, 선점 검사). + 시계, 운영자, 이벤트 기록."""
from __future__ import annotations

import dataclasses
import json
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from .blackboard import Blackboard, ProgramError
from .skill import Aborted, Cancelled, GuardFired
from .types import Decision


# ---------- 시계 ----------
class RealClock:
    def now(self) -> float:
        return time.monotonic()

    def sleep(self, dt: float) -> None:
        time.sleep(dt)


class VirtualClock:
    """가짜 로봇용: 기다리지 않고 시간만 흘린다."""

    def __init__(self) -> None:
        self._t = 0.0
        self._lock = threading.Lock()

    def now(self) -> float:
        return self._t

    def sleep(self, dt: float) -> None:
        with self._lock:
            self._t += dt


# ---------- 이벤트 기록: 실행 1회 = JSONL 파일 1개 ----------
def _plain(v: Any) -> Any:
    if isinstance(v, BaseModel):
        return v.model_dump(exclude={"rgb", "depth"})
    if isinstance(v, dict):
        return {k: _plain(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_plain(x) for x in v]
    if isinstance(v, float):
        return round(v, 5)
    if isinstance(v, (str, int, bool)) or v is None:
        return v
    return str(v)


class EventLog:
    def __init__(self, path: str | Path | None = None, clock=None) -> None:
        self.records: list[dict] = []
        self.clock = clock or RealClock()
        self._t0 = self.clock.now()
        self._lock = threading.Lock()
        self._file = None
        if path is not None:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            self._file = open(path, "w", buffering=1)

    def emit(self, event: str, **data: Any) -> None:
        rec = {"t": round(self.clock.now() - self._t0, 3), "ev": event, **_plain(data)}
        with self._lock:
            self.records.append(rec)
            if self._file is not None:
                self._file.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def close(self) -> None:
        if self._file is not None:
            self._file.close()
            self._file = None

    def of(self, event: str) -> list[dict]:
        return [r for r in self.records if r["ev"] == event]


# ---------- 운영자 ----------
class ScriptedOperator:
    """시험·데모용: 미리 적어 둔 답을 차례로 낸다. 답이 떨어지면 `default`."""

    def __init__(self, answers: list | None = None, default: str = "abort") -> None:
        self.answers = list(answers or [])
        self.default = default
        self.asked: list[str] = []

    def ask(self, prompt: str, allowed: list[str], ctx: "Context") -> Decision:
        self.asked.append(prompt)
        a = self.answers.pop(0) if self.answers else self.default
        if callable(a):
            a = a(prompt, allowed, ctx)
        d = a if isinstance(a, Decision) else Decision(choice=str(a))
        if d.choice not in allowed and not self.answers and a is self.default:
            d = Decision(choice=allowed[0])        # 기본 답이 선택지에 없으면 첫 선택지
        return d


class ConsoleOperator:
    """키보드. 허용 명령 이름을 그대로 치거나, 줄임:
    `l/r/f/b [m]`, `tl/tr [deg]` = move, `d` = continue, `q` = stop. 숫자를 치면 그 번째 선택지."""

    MOVES = {"l": ("dy", 1), "r": ("dy", -1), "f": ("dx", 1), "b": ("dx", -1), "tl": ("dyaw", 1), "tr": ("dyaw", -1)}

    def ask(self, prompt: str, allowed: list[str], ctx: "Context") -> Decision:
        import math
        print(f"\n[게이트] {prompt}\n  허용: {' / '.join(allowed)}   (l/r/f/b [m], tl/tr [deg], d=continue, q=stop, 숫자=그 번째)")
        while True:
            parts = input("> ").strip().lower().split()
            if not parts:
                continue
            cmd = parts[0]
            if cmd == "q" and "stop" in allowed:
                return Decision(choice="stop")
            if cmd.isdigit() and 1 <= int(cmd) <= len(allowed):
                return Decision(choice=allowed[int(cmd) - 1])
            if cmd == "d" and "continue" in allowed:
                return Decision(choice="continue")
            if cmd in self.MOVES and "move" in allowed:
                axis, sign = self.MOVES[cmd]
                try:
                    amount = float(parts[1]) if len(parts) > 1 else (5.0 if axis == "dyaw" else 0.05)
                except ValueError:
                    print("  숫자를 읽을 수 없다")
                    continue
                if axis == "dyaw":
                    amount = math.radians(amount)
                return Decision(choice="move", args={"dx": 0.0, "dy": 0.0, "dyaw": 0.0, axis: sign * amount})
            if cmd in allowed:
                return Decision(choice=cmd)
            print("  허용되지 않는 명령")


# ---------- 파트 점유: 같은 파트를 두 동작이 동시에 못 쓴다 ----------
class Resources:
    def __init__(self) -> None:
        self._held: dict[str, str] = {}
        self._lock = threading.Lock()

    def acquire(self, parts: frozenset[str], owner: str) -> None:
        with self._lock:
            clash = [p for p in parts if p in self._held]
            if clash:
                raise ProgramError(f"파트 충돌: {owner} 가 {clash} 를 쓰려는데 {self._held[clash[0]]} 가 쓰는 중")
            for p in parts:
                self._held[p] = owner

    def release(self, parts: frozenset[str]) -> None:
        with self._lock:
            for p in parts:
                self._held.pop(p, None)


# ---------- Context ----------
@dataclass
class Guard:
    name: str
    cond: Any
    inp: Any
    then: Any = None             # 걸리면 탈 갈림 (runtime.nodes.Branch)


@dataclass
class Context:
    robot: Any
    bb: Blackboard
    registry: Any
    events: EventLog
    operator: Any
    clock: Any
    stop: threading.Event
    resources: Resources
    store: dict = field(default_factory=dict)     # 과제 장부(ExpectedZ 등)가 실행 내내 들고 있는 것
    dt: float = 0.01
    guards: tuple = ()
    cancels: tuple = ()
    scope_guards: tuple = ()                      # 모듈에 꽂힌 조건 블록 (그 안의 블록 전부에 걸린다)
    at: str = ""                                  # 지금 도는 블록의 노드 id

    @property
    def params(self) -> dict:
        return self.bb.get("params")

    def derive(self, **kw: Any) -> "Context":
        return dataclasses.replace(self, **kw)

    def emit(self, event: str, **data: Any) -> None:
        self.events.emit(event, **data)

    def check(self) -> None:
        """긴 동작이 매 tick 부른다: 정지 요청 / E-stop → Aborted."""
        if self.stop.is_set():
            raise Aborted("stop")
        for c in self.cancels:
            if c.is_set():
                raise Cancelled()
        self.robot.check()

    def poll(self) -> str | None:
        """가드를 한 번씩 묻고, 울린 가드의 이름을 돌려준다."""
        for g in self.guards:
            if g.cond.check(self, g.inp):
                return g.name
        return None

    # ---- 파이썬 블록이 다른 블록을 부르거나 운영자에게 물을 때 (파트 점유·이벤트가 똑같이 걸린다) ----
    def call(self, skill: str, **inputs: Any) -> Any:
        cls = self.registry.skills[skill]
        inp = cls.Input(**inputs)
        node, parts = f"{self.at}>{skill}", cls.requires_for(inp)
        self.emit("node_enter", node=node, type=skill)
        self.resources.acquire(parts, node)
        try:
            res = cls().run(self.derive(at=node), inp)      # 겉 블록에 꽂힌 조건 블록이 안쪽 동작에도 걸린다
        finally:
            self.resources.release(parts)
        self.emit("node_exit", node=node, type=skill, status=res.status, **({"reason": res.reason} if res.reason else {}))
        fired = getattr(res, "stopped_by", None)
        if fired in {g.name for g in self.guards}:
            raise GuardFired(fired)
        return res

    def ask(self, prompt: str, allowed: list[str], node: str | None = None) -> Decision:
        node = node or self.at
        self.emit("gate", node=node, prompt=prompt, allowed=allowed)
        d = self.operator.ask(prompt, allowed, self)
        if d.choice not in allowed:
            raise ProgramError(f"{node}: 운영자 답 {d.choice!r} 는 선택지가 아니다 {allowed}")
        self.emit("decision", node=node, choice=d.choice, args=d.args)
        return d

    def now(self) -> float:
        return self.clock.now()

    def sleep(self, dt: float) -> None:
        self.clock.sleep(dt)
