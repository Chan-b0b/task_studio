"""Task Studio ① 기본 층: 스킬 계약, 런타임, 파트 인터페이스, 과제와 무관한 블록. 과제 층을 import 하지 않는다."""
from pathlib import Path

import yaml

from .core.registry import Registry

HERE = Path(__file__).parent


def base_registry() -> Registry:
    from .skills import motion, sense
    from .core import types as T
    reg = Registry()
    reg.add_types_file(HERE / "types.yaml", "base", py={n: getattr(T, n) for n in
                       ("Pose", "JointState", "Wrench", "Frame", "ObjectPose", "Station", "Decision")})
    reg.add_module(motion, "base")
    reg.add_module(sense, "base")
    reg.add_yaml_dir(HERE / "macros", "base")
    reg.check_skills()
    return reg


def base_params() -> dict:
    return yaml.safe_load((HERE / "params.yaml").read_text(encoding="utf-8"))
