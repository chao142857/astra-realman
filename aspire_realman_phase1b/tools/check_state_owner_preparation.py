"""Boundary checks using an explicitly historical state, never live hardware."""
import argparse
import copy
import hashlib
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
path = ROOT / "aspire_realman_phase1a/src/aspire_realman_live/state_owner.py"
spec = importlib.util.spec_from_file_location("prepared_state_owner", path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.resolve().relative_to(ROOT)
    if args.output.exists():
        raise RuntimeError("NEW_REPORT_REQUIRED")
    source = ROOT / "aspire_realman_phase0/evidence/replay_snapshot.json"
    canonical = json.loads(source.read_text())["canonical_states"]["left"]
    sample = {"arm": "left", "canonical": canonical, "calls": {}}

    def fresh_owner():
        return module.SingleArmStateOwner("offline-contract-check", "left", source_kind="HISTORICAL_REPLAY", clock_id="test-clock")

    owner = fresh_owner()
    owner.publish(sample, owner_id=owner.owner_id, sequence=1, read_interval_monotonic_s=[100, 100.02], host_clock_id="test-clock")
    view = owner.read(now_monotonic_s=100.03, now_epoch_s=canonical["timestamp"]+10000, host_clock_id="test-clock")
    assert not view["quality"]["live_host_time_eligible"] and not view["native_robot_state_available"]
    assert view["joint_velocity_deg_s"] is None and view["world_transform"] is None and view["actual_grasp_tcp"] is None
    original = owner.read(now_monotonic_s=100.03, now_epoch_s=canonical["timestamp"], host_clock_id="test-clock")
    original["canonical_state"]["joint_deg"][0] = 999
    assert owner.read()["canonical_state"]["joint_deg"][0] != 999
    errors = {}
    for label, mutate in {
        "wrong_arm": lambda s: s.update(arm="right"),
        "changed_frame": lambda s: s["canonical"].update(frame_snapshot_stable=False),
        "bad_units": lambda s: s["canonical"]["ee_pose"].update(units={"xyz": "mm", "rpy": "rad"}),
    }.items():
        bad = copy.deepcopy(sample)
        mutate(bad)
        target = fresh_owner()
        try:
            target.publish(bad, owner_id=target.owner_id, sequence=1, read_interval_monotonic_s=[100,100.02], host_clock_id="test-clock")
        except ValueError as exc:
            errors[label] = str(exc)
        else:
            raise AssertionError("Invalid sample accepted")
    for label, fn in {"connect": owner.connect, "start": owner.start, "poll": owner.poll_once, "native_state": owner.as_native_state}.items():
        try:
            fn()
        except RuntimeError as exc:
            errors[label] = str(exc)
        else:
            raise AssertionError("Hardware/native gate did not refuse")
    # A fabricated receipt on an old historical payload still cannot make it live.
    live = module.SingleArmStateOwner("live-contract-fault-injection", "left", source_kind="LIVE_SDK_READ_ONLY", clock_id="test-clock")
    try:
        live.publish(sample, owner_id=live.owner_id, sequence=1, read_interval_monotonic_s=[100,100.02], host_clock_id="test-clock")
    except ValueError as exc:
        errors["history_without_five_sdk_reads"] = str(exc)
    else:
        raise AssertionError("Historical data masqueraded as live")
    bounds = module.camera_state_receipt_bounds_ms([100,100.01],[100.015,100.03],camera_clock="test",state_clock="test")
    assert abs(bounds["minimum_ms"]-5)<1e-8 and abs(bounds["maximum_ms"]-30)<1e-8
    mismatch = module.camera_state_receipt_bounds_ms([100,100.01],[100.015,100.03],camera_clock="camera-device",state_clock="test")
    assert not mismatch["comparable"]
    wrong_clock_view = owner.read(now_monotonic_s=100.03, now_epoch_s=canonical["timestamp"], host_clock_id="different-host")
    assert wrong_clock_view["quality"]["source_epoch_age_s"] is None
    try:
        owner.publish(sample, owner_id=owner.owner_id, sequence=1, read_interval_monotonic_s=[100,100.02], host_clock_id="test-clock")
    except ValueError as exc:
        errors["repeated_sample"] = str(exc)
    else:
        raise AssertionError("Repeated sequence accepted")
    assert not owner.read()["quality"]["owner_running"]
    result = {"status": "OFFLINE_OWNER_CONTRACT_PREPARATION_PASS_NOT_LIVE_INTEGRATION", "arm_scope": ["left"],
        "input_source": {"path": str(source), "sha256": hashlib.sha256(source.read_bytes()).hexdigest(), "kind": "HISTORICAL_REPLAY"},
        "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "refusals": errors,
        "missing_velocity_preserved_as_null": True, "historical_state_not_freshened": True,
        "receipt_bounds_ms": bounds, "different_time_domains_not_subtracted": mismatch,
        "sdk_imports": 0, "hardware_connections": 0, "motion_dispatches": 0,
        "current_robot_state": None, "native_cap_observation_available": False}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
