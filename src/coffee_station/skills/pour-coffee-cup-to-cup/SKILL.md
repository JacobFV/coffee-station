---
name: pour-coffee-cup-to-cup
description: Use to pour coffee or liquid from a held source cup into a target cup using camera feedback, calibration, staged IK movements, and scheduled tilt motions.
---

# Pour Coffee Cup To Cup

This is a high-level routine. Use camera feedback and calibration before motion. If the source cup is not already grasped, first use a cup grasping routine or ask the operator to place the cup in the gripper.

## Preconditions

- Source cup is securely held or ready to grasp.
- Target cup center is visible in at least one enabled camera.
- `get_calibration` has at least three samples when precise pouring matters.
- No people or fragile objects are inside the arm workspace.

## Routine

1. Call `get_robot_state`, `list_cameras`, and `get_calibration`.
2. If camera alignment is uncertain, request a latest frame with `request_latest_frame`.
3. Move to `pour-prep` or an equivalent world pose above the source/target path.
4. Move above the target cup center using `set_world_pose` with a safe height margin of 5-8 cm above the rim.
5. Use small `offset_world_pose` corrections until the gripper/cup lip is aligned over the target cup opening.
6. Use `bundle_tool_calls` to perform the pour:
   - hold above target at `offset_s: 0`
   - tilt lightly at `offset_s: 0.5`
   - tilt stronger only if needed at `offset_s: 1.5`
   - return upright at `offset_s: 3.0`
   - lift up 3-5 cm at `offset_s: 3.5`
7. Request a camera frame after the tilt returns upright.
8. If liquid remains and the target is safe, repeat a shorter tilt. Otherwise return to `carry-cup` or `home`.

## Safety Rules

- Do not pour if the target cup is not visible.
- Do not pour from a high tilt while the cup lip is outside the target cup boundary.
- Prefer a short test pour before a full pour.
- Stop immediately with `stop_robot` if the cup slips or the target moves.
