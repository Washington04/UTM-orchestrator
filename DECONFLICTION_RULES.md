# Deconfliction Rules

## Primary resolution order
1. Prefer altitude change first.
2. If altitude change is insufficient or not available, prefer a time delay.
3. A time delay may be applied either:
   - on the ground, if the delay can resolve the conflict without introducing new conflicts, or
   - in flight by adjusting speed so the aircraft arrives at the conflicting volume at a deconflicted time.
4. Ground-path changes are not allowed automatically. A ground-path change requires explicit user approval before it is implemented.

## Decision policy
- Treat altitude change as the default first response for any detected conflict.
- Use time delay only when altitude change alone is not sufficient.
- If a delay occurs on the ground, ensure that the delay does not create new conflicts with other volumes, waypoints, or constraints.
- If a delay is achieved by changing speed, ensure the adjusted trajectory remains within operational limits and does not create a new conflict.
- Any path re-routing on the ground must be treated as a human-approval-required action.

## Agent guidance
When generating a conflict-resolution recommendation:
- Start with an altitude change recommendation.
- If altitude is constrained, propose a time delay.
- If time delay is chosen, explain whether it is a ground delay or an in-flight speed adjustment.
- If a ground-path change is considered, mark it as pending user approval and do not execute it automatically.
