"""Vega 하드웨어 어댑터 (dexcontrol 직접). 아직 없다.

채워야 할 것은 parts/robot.py 의 인터페이스 그대로다:
  arm(side).move_ee / reachable   ← IK(pink/pinocchio) + 직선·수직 스트림
  joints.move                      ← ruckig 관절 보간
  chassis.move                     ← 속도×시간 / odometry
  suction.on / off / sealed        ← DIO
  wrist(side).read                 ← 손목 힘센서, tare
  camera / detector                ← ZED 머리 카메라, 과제가 등록한 검출기
"""


def connect(*args, **kwargs):
    raise NotImplementedError("Vega 어댑터는 아직 없다. --robot mock 으로 돌린다.")
