---
name: pose-table-6dof
description: Use when the arm needs known 6-DoF joint-space poses such as fully extended, fully retracted, home, carry, cup approach, or pour prep.
---

# 6-DoF Pose Table

Use these as named joint-space references for `set_joint_pose`. Values are degrees in the harness order:

`[base, shoulder, elbow, wrist_pitch, wrist_roll, gripper]`

The exact hardware may differ. Treat these as conservative starting points and prefer small scheduled transitions between them.

| Pose | joints | Purpose |
| --- | --- | --- |
| home | `[0, -25, 35, -10, 0, 35]` | Neutral visible pose. |
| fully-retracted | `[0, -62, 92, -35, 0, 35]` | Arm folded inward with gripper clear of the table. |
| fully-extended | `[0, 18, -28, 10, 0, 35]` | Straight reach in front of the base. Use slowly. |
| carry-cup | `[0, -18, 48, -28, 0, 18]` | Elbow bent, cup held above table. |
| cup-approach | `[0, -8, 42, -34, 0, 55]` | Open gripper approach near a cup. |
| cup-grasp | `[0, -8, 42, -34, 0, 12]` | Close gripper around cup. Tune gripper for cup diameter. |
| pour-prep | `[0, -15, 45, -28, 0, 12]` | Cup held upright before moving over target. |
| pour-tilt-light | `[0, -12, 42, -45, 55, 12]` | Gentle pour tilt. |
| pour-tilt-strong | `[0, -8, 38, -55, 82, 12]` | Strong pour tilt. Use only after alignment. |

## Procedure

1. Before using `fully-extended` or any pour tilt, call `get_robot_state`.
2. Schedule transitions with `bundle_tool_calls`; do not jump straight from retracted to a pour pose.
3. Use `duration_s >= 0.8` for large joint changes and `duration_s >= 0.25` for small corrections.
4. If camera feedback shows drift or collision risk, call `stop_robot` and reassess.
