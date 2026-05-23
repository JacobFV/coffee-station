---
name: gripper-world-calibration
description: Use to calibrate real-world object positions against the arm's believed gripper coordinate frame using comparison points and small IK moves.
---

# Gripper World Calibration

Goal: estimate the offset between requested world-space gripper targets and the real measured gripper/tool position.

Use the calibration tools:

- `record_calibration_point`: save a believed target and measured actual tool position.
- `get_calibration`: inspect current offset and sample count.
- `clear_calibration`: reset bad calibration data.
- `set_world_pose` and `offset_world_pose`: test corrected targets.

## Routine

1. Move to a visible safe target with `set_world_pose`.
2. Ask for or infer the actual gripper/tool position from camera or operator measurement.
3. Call `record_calibration_point` with:
   - `believed_x`, `believed_y`, `believed_z`: the commanded target.
   - `actual_x`, `actual_y`, `actual_z`: the measured gripper/tool position in the same world frame.
4. Repeat with at least three positions spanning the work area: near-left, near-right, and forward.
5. Call `get_calibration`; the harness will compute mean XYZ offsets as `actual - believed`.
6. When targeting a real object, compensate by requesting `target - offset` so the physical gripper lands near the target.

## Rules

- Keep each calibration move small and visible.
- Never calibrate from a collision, slip, or occluded camera frame.
- Prefer table-height points first, then add elevated points.
- If new points disagree strongly with previous points, call `clear_calibration` and restart.
