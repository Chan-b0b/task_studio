"""스킬 계약. 동작 = run(ctx, inp) → Result, 조건 = check(ctx, inp) → bool."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict

from .types import Pose

if TYPE_CHECKING:
    from .context import Context


class Result(BaseModel):
    model_config = ConfigDict(extra="allow")     # 매크로의 returns 필드가 여기에 붙는다
    status: Literal["ok", "fail", "stopped", "aborted"] = "ok"
    reason: str = ""


class ActionResult(Result):
    stopped_by: str = "reached"                  # reached / <가드 이름> / unreachable / aborted
    pose_at_stop: Pose | None = None


class Value(Result):
    """값 하나를 내는 블록(Pose, 숫자, 문자열 …). `out: $x` 에는 value 가 그대로 들어간다."""
    value: Any = None


class NoInput(BaseModel):
    pass


class Aborted(Exception):
    """정지 요청 / 운영자 abort / E-stop. 실행기가 받아서 on_abort 트리를 돌린다."""


class Stopped(Exception):
    """갈림의 끝이 멈춤이거나 블록이 실패했다. 프로그램이 그 자리에서 끝난다 (on_abort 는 돌지 않는다)."""


class GuardFired(Exception):
    """파이썬 블록이 안에서 부른 동작이 겉에 꽂힌 조건 블록에 걸렸다. 블록을 그 자리에서 접고 조건 블록의 갈림을 탄다."""
    def __init__(self, name: str) -> None:
        super().__init__(name)
        self.name = name


class Again(Exception):
    """갈림의 끝이 again: 감싸고 있는 Loop 상자의 처음으로."""


class Cancelled(Exception):
    """Parallel(any) 에서 다른 가지가 먼저 끝나 이 가지를 접을 때."""


class Unreachable(Exception):
    """IK 가 목표를 못 푼다. 동작 스킬이 받아 stopped_by='unreachable' 로 돌려준다."""


class Skill:
    name: ClassVar[str]
    kind: ClassVar[str] = "action"               # action / condition
    layer: ClassVar[str] = "base"                # base / task
    part: ClassVar[str] = ""                     # 블록 목록 표의 "파트" 열
    Input: ClassVar[type[BaseModel]] = NoInput
    Output: ClassVar[type[Result]] = Result
    requires: ClassVar[frozenset[str]] = frozenset()   # 병렬 실행 시 충돌 검사
    slots: ClassVar[dict[str, str]] = {}         # 입력 칸 이름 → 타입 이름 (types.yaml). Input 의 모든 필드에 적는다
    gives: ClassVar[str | None] = None           # 출력의 타입 이름. 내는 것이 없으면 None

    @classmethod
    def requires_for(cls, inp: BaseModel) -> frozenset[str]:
        return cls.requires

    def run(self, ctx: "Context", inp: BaseModel) -> Result:
        raise NotImplementedError


class Action(Skill):
    Output = ActionResult

    def drive(self, ctx: "Context", motion) -> str:
        """Motion 을 끝까지 굴린다. 매 tick: 선점 검사 → 가드 → 한 걸음. 돌려주는 것은 stopped_by."""
        while True:
            ctx.check()
            fired = ctx.poll()
            if fired:
                motion.stop()
                return fired
            if motion.step(ctx.dt):
                return ctx.poll() or "reached"      # 목표에 닿는 순간 조건도 걸렸으면 조건이 이긴다
            ctx.sleep(ctx.dt)


class Condition(Skill):
    kind = "condition"

    def arm(self, ctx: "Context", inp: BaseModel) -> None:
        """가드로 꽂혔을 때 동작 시작 직전에 한 번 (기준값·시작 시각 잡기)."""

    def check(self, ctx: "Context", inp: BaseModel) -> bool:
        raise NotImplementedError
