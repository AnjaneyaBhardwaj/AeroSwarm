import pytest
from pydantic import ValidationError

from swarm.state import PLACEHOLDER_CAR, DesignSpec, ReferenceCar, WingParams, speed_for_reynolds


def test_reynolds_is_derived_from_speed_and_chord(spec):
    assert spec.reynolds == pytest.approx(8.3e5, rel=1e-9)
    faster = spec.model_copy(update={"speed_mps": spec.speed_mps * 2})
    assert DesignSpec.model_validate(faster.model_dump()).reynolds == pytest.approx(1.66e6)
    big = PLACEHOLDER_CAR.model_copy(update={"chord_mm": 600.0})
    s = DesignSpec(component="wing_1el", target_cl=-1.5, cd_max=0.018, speed_mps=spec.speed_mps, car=big)
    assert s.reynolds == pytest.approx(1.66e6)


def test_reynolds_cannot_be_set_independently(spec):
    with pytest.raises(ValidationError, match="derived"):
        DesignSpec(component="wing_1el", target_cl=-1.5, cd_max=0.018, speed_mps=40.0, reynolds=1e6)
    # a dump (which includes the computed value) round-trips
    assert DesignSpec.model_validate(spec.model_dump()) == spec


def test_demo_speed_gives_re_near_8_3e5():
    from swarm.run import DEMO_SPEC

    assert DEMO_SPEC.reynolds == pytest.approx(8.3e5, rel=1e-3)
    assert speed_for_reynolds(8.3e5, 300.0) == pytest.approx(41.5, abs=0.01)  # ν = 1.5e-5


def test_spec_is_frozen(spec):
    with pytest.raises(ValidationError):
        spec.target_cl = -1.3


def test_params_quantized_before_cid():
    a = WingParams(main_camber=0.04, main_camber_pos=0.4, main_thickness=0.12, alpha_deg=8.0)
    b = WingParams(main_camber=0.04000004, main_camber_pos=0.4, main_thickness=0.12, alpha_deg=8.00003)
    c = WingParams(main_camber=0.04, main_camber_pos=0.4, main_thickness=0.12, alpha_deg=8.0002)
    assert a.cid == b.cid
    assert b.alpha_deg == 8.0 and b.main_camber == 0.04  # the evaluated geometry is the quantized one
    assert a.cid != c.cid


def test_cross_constraint_and_bounds():
    with pytest.raises(ValidationError, match="no flap element"):
        WingParams(main_camber=0.04, main_camber_pos=0.4, main_thickness=0.12, alpha_deg=8, flap_deflection_deg=10)
    with pytest.raises(ValidationError):
        WingParams(main_camber=0.04, main_camber_pos=0.4, main_thickness=0.25, alpha_deg=8)
    assert WingParams.bounds()["alpha_deg"] == (-2.0, 14.0)


def test_reference_car_frozen():
    car = ReferenceCar(head_restraint_x=1, rear_tire_rear_x=2, wing_mount_x=3, wing_mount_z=4, inner_rear_track_mm=5)
    with pytest.raises(ValidationError):
        car.chord_mm = 1.0
