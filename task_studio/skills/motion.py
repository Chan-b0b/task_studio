"""① 기본 — 움직이는 원자 블록: 팔·몸통·머리, 섀시, 석션, 기다림. 액추에이터 하나, 판단 없음."""
from __future__ import annotations

from pydantic import BaseModel

from ..core.skill import Action, ActionResult, Result, Skill, Unreachable
from ..core.types import Pose


class MoveJoints(Action):
    name, part = "MoveJoints", "팔·몸통·머리"
    slots, gives = {"group": "PartName", "q": "JointAngles", "speed": "Speed"}, "MoveResult"

    class Input(BaseModel):
        group: str                      # left_arm / right_arm / torso / head
        q: list[float]
        speed: float = 0.5              # 속도 배율 0~1

    class Output(ActionResult):
        q: list[float] = []

    @classmethod
    def requires_for(cls, inp):
        return frozenset({inp.group})

    def run(self, ctx, inp):
        stopped_by = self.drive(ctx, ctx.robot.joints.move(inp.group, inp.q, inp.speed))
        return self.Output(stopped_by=stopped_by, q=ctx.robot.joints.q(inp.group))


class MoveEE(Action):
    name, part = "MoveEE", "팔"
    slots, gives = {"pose": "Pose", "arm": "PartName", "straight": "bool", "keep_xy": "bool", "speed": "Speed"}, "MoveResult"

    class Input(BaseModel):
        pose: Pose
        arm: str = "left"
        straight: bool = False          # True = 직선, False = 관절 공간 호
        keep_xy: bool = False           # 수직 전용: 지금 x, y, 방향은 두고 z 만 pose.z 로
        speed: float | None = None      # m/s. 없으면 params.ee_speed

    class Output(ActionResult):
        error_m: float = 0.0

    @classmethod
    def requires_for(cls, inp):
        return frozenset({f"{inp.arm}_arm"})

    def run(self, ctx, inp):
        arm = ctx.robot.arm(inp.arm)
        target = inp.pose
        if inp.keep_xy:
            target = arm.ee_pose().model_copy(update={"z": inp.pose.z})
        speed = inp.speed if inp.speed is not None else float(ctx.params["ee_speed"])
        try:
            motion = arm.move_ee(target, straight=inp.straight or inp.keep_xy, speed=speed)
        except Unreachable as e:
            ctx.emit("unreachable", skill=self.name, detail=str(e))
            return self.Output(status="fail", reason="unreachable", stopped_by="unreachable", pose_at_stop=arm.ee_pose())
        stopped_by = self.drive(ctx, motion)
        at = arm.ee_pose()
        return self.Output(stopped_by=stopped_by, pose_at_stop=at, error_m=abs(at.z - target.z) if stopped_by == "reached" else 0.0)


class BaseMove(Action):
    name, part = "BaseMove", "섀시"
    slots, gives = {"dx": "Distance", "dy": "Distance", "dyaw": "Angle", "speed": "Speed"}, "MoveResult"
    requires = frozenset({"chassis"})

    class Input(BaseModel):
        dx: float = 0.0                 # 앞(+) / 뒤
        dy: float = 0.0                 # 왼(+) / 오른
        dyaw: float = 0.0
        speed: float | None = None      # m/s. 없으면 params.chassis_speed

    class Output(ActionResult):
        dx: float = 0.0
        dy: float = 0.0
        dyaw: float = 0.0

    def run(self, ctx, inp):
        speed = inp.speed if inp.speed is not None else float(ctx.params["chassis_speed"])
        stopped_by = self.drive(ctx, ctx.robot.chassis.move(inp.dx, inp.dy, inp.dyaw, speed))
        settle = float(ctx.params.get("chassis_settle_s", 0.0))
        if settle:
            ctx.sleep(settle)
        return self.Output(stopped_by=stopped_by, dx=inp.dx, dy=inp.dy, dyaw=inp.dyaw)


class SuctionOn(Skill):
    name, part = "SuctionOn", "석션"
    slots, gives = {}, None
    requires = frozenset({"suction"})

    def run(self, ctx, inp):
        ctx.robot.suction.on()
        return Result()


class SuctionOff(Skill):
    name, part = "SuctionOff", "석션"
    slots, gives = {"blow": "bool"}, None
    requires = frozenset({"suction"})

    class Input(BaseModel):
        blow: bool = False              # 불어서 떼기

    def run(self, ctx, inp):
        ctx.robot.suction.off(blow=inp.blow)
        return Result()


class Wait(Action):
    name, part = "Wait", "타이머"
    slots, gives = {"s": "Seconds"}, "MoveResult"

    class Input(BaseModel):
        s: float | None = None          # 이만큼 기다리면 "도달". 없으면 조건 블록에 걸릴 때까지

    class Output(ActionResult):
        elapsed: float = 0.0

    def run(self, ctx, inp):
        t0 = ctx.now()
        while True:
            ctx.check()
            fired = ctx.poll()
            if fired or (inp.s is not None and ctx.now() - t0 >= inp.s):
                return self.Output(stopped_by=fired or "reached", elapsed=ctx.now() - t0)
            ctx.sleep(ctx.dt)


class OperatorDrive(Skill):
    """운영자가 섀시를 원하는 자리에 세운다. move 를 낼 때마다 그만큼 움직이고 다시 묻는다.
    continue = 다 됐다, stop = 그만(블록 실패 → 프로그램이 멈춘다)."""
    name, part = "OperatorDrive", "운영자·섀시"
    slots, gives = {"prompt": "Message"}, None

    class Input(BaseModel):
        prompt: str = "섀시 위치를 맞춘다"

    def run(self, ctx, inp):
        while True:
            d = ctx.ask(inp.prompt, ["move", "continue", "stop"])
            if d.choice == "continue":
                return Result()
            if d.choice == "stop":
                return Result(status="fail", reason="operator_stop")
            ctx.call("BaseMove", dx=d.args.get("dx", 0.0), dy=d.args.get("dy", 0.0), dyaw=d.args.get("dyaw", 0.0),
                     speed=float(ctx.params["chassis_manual_speed"]))
