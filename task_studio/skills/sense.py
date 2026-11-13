"""① 기본 — 보고 재는 블록, 순수 계산 블록, 조건 블록."""
from __future__ import annotations

import math

from pydantic import BaseModel

from ..core.skill import Condition, Result, Skill, Value
from ..core.types import Frame, ObjectPose, Pose


# ------------------------------------------------------------ 보기 / 재기
class CaptureFrame(Skill):
    name, part = "CaptureFrame", "머리 카메라"
    slots, gives = {"camera": "PartName"}, "Frame"

    class Input(BaseModel):
        camera: str = "head"

    def run(self, ctx, inp):
        return Value(value=ctx.robot.camera(inp.camera).capture())


class Detect(Skill):
    name, part = "Detect", "머리 카메라"
    slots, gives = {"cls": "ObjectClass", "detector": "PartName", "frame": "Frame", "camera": "PartName"}, "Detections"

    class Input(BaseModel):
        cls: str
        detector: str = "bev"
        frame: Frame | None = None      # 없으면 직접 찍는다
        camera: str = "head"

    def run(self, ctx, inp):
        frame = inp.frame or ctx.robot.camera(inp.camera).capture()
        return Value(value=ctx.robot.detector(inp.detector).detect(frame, inp.cls))


class ReadWrench(Skill):
    name, part = "ReadWrench", "손목 센서"
    slots, gives = {"arm": "PartName"}, "Wrench"

    class Input(BaseModel):
        arm: str = "left"

    def run(self, ctx, inp):
        return Value(value=ctx.robot.wrist(inp.arm).read())


class TareWrench(Skill):
    name, part = "TareWrench", "손목 센서"
    slots, gives = {"arm": "PartName", "samples": "Count"}, "Wrench"

    class Input(BaseModel):
        arm: str = "left"
        samples: int = 20

    def run(self, ctx, inp):
        fz = 0.0
        for _ in range(inp.samples):
            fz += ctx.robot.wrist(inp.arm).read().fz
            ctx.sleep(ctx.dt)
        base = fz / max(inp.samples, 1)
        ctx.store.setdefault("wrench_tare", {})[inp.arm] = base
        return Value(value=base)


# ------------------------------------------------------------ 계산
class OffsetPose(Skill):
    name, part = "OffsetPose", "(계산)"
    slots, gives = {"pose": "Pose", "dx": "Distance", "dy": "Distance", "dz": "Distance", "dyaw": "Angle", "frame": "Option"}, "Pose"

    class Input(BaseModel):
        pose: Pose
        dx: float = 0.0
        dy: float = 0.0
        dz: float = 0.0
        dyaw: float = 0.0
        frame: str = "base"             # base = base_link 축 / pose = 그 Pose 의 yaw 를 따라 돌린 축

    def run(self, ctx, inp):
        dx, dy = inp.dx, inp.dy
        if inp.frame == "pose":
            c, s = math.cos(inp.pose.yaw), math.sin(inp.pose.yaw)
            dx, dy = c * inp.dx - s * inp.dy, s * inp.dx + c * inp.dy
        p = inp.pose
        return Value(value=p.model_copy(update={"x": p.x + dx, "y": p.y + dy, "z": p.z + inp.dz, "yaw": p.yaw + inp.dyaw}))


class GraspPose(Skill):
    """ObjectPose → 툴 끝이 물체 윗면 가운데에, 물체 yaw 에 맞춰 내려다보는 EE Pose."""
    name, part = "GraspPose", "(계산)"
    slots, gives = {"det": "ObjectPose", "approach": "Option", "point": "Option"}, "Pose"

    class Input(BaseModel):
        det: ObjectPose
        approach: str = "top"           # top / side
        point: str = "center"           # center / edge

    def run(self, ctx, inp):
        if inp.approach != "top" or inp.point != "center":
            return Result(status="fail", reason="not_implemented")      # 같이 정할 것 #9
        d = inp.det.pose
        return Value(value=Pose(x=d.x, y=d.y, z=d.z + float(ctx.params["tool_length"]),
                                roll=math.pi, pitch=0.0, yaw=d.yaw + math.pi))


# ------------------------------------------------------------ 조건
class ForceOver(Condition):
    name, part = "ForceOver", "손목 센서"
    slots, gives = {"threshold": "Force", "axis": "Option", "relative": "bool", "arm": "PartName"}, None

    class Input(BaseModel):
        threshold: float                # N
        axis: str = "z"
        relative: bool = True           # True = 동작 시작 때의 힘에서 변한 양
        arm: str = "left"

    def arm(self, ctx, inp):
        self.base = getattr(ctx.robot.wrist(inp.arm).read(), "f" + inp.axis) if inp.relative else 0.0

    def check(self, ctx, inp):
        self.last = getattr(ctx.robot.wrist(inp.arm).read(), "f" + inp.axis)
        return abs(self.last - self.base) > inp.threshold


class Sealed(Condition):
    name, part = "Sealed", "석션"
    slots, gives = {}, None

    def check(self, ctx, inp):
        return ctx.robot.suction.sealed()


class Timeout(Condition):
    name, part = "Timeout", "타이머"
    slots, gives = {"s": "Seconds"}, None

    class Input(BaseModel):
        s: float

    def arm(self, ctx, inp):
        self.t0 = ctx.now()

    def check(self, ctx, inp):
        return ctx.now() - self.t0 >= inp.s


class Reachable(Condition):
    name, part = "Reachable", "팔"
    slots, gives = {"pose": "Pose", "down_to": "Height", "step": "Distance", "arm": "PartName"}, None

    class Input(BaseModel):
        pose: Pose
        down_to: float | None = None    # 주면 pose.z 에서 이 높이까지의 기둥 전체를 본다
        step: float = 0.02
        arm: str = "left"

    def check(self, ctx, inp):
        arm = ctx.robot.arm(inp.arm)
        zs = [inp.pose.z]
        if inp.down_to is not None:
            top = max(arm.ee_pose().z, inp.down_to)
            n = max(1, math.ceil((top - inp.down_to) / inp.step))
            zs = [top - i * (top - inp.down_to) / n for i in range(n + 1)]
        for z in zs:
            ok, err = arm.reachable(inp.pose.model_copy(update={"z": z}))
            if not ok:
                ctx.emit("unreachable", skill=self.name, z=z, error_m=err, x=inp.pose.x, y=inp.pose.y)
                return False
        return True
