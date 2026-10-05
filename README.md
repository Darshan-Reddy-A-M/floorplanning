# Architectural Test-Fit Generator

Preliminary residential test-fit tool built with Python, Google OR-Tools
CP-SAT, Streamlit, and Matplotlib. Room-program recommendations are transparent
rules, not machine learning or professional design advice.

## Run the application

```bash
streamlit run app.py --server.port 5000 --server.address 0.0.0.0 --server.headless true --server.showEmailPrompt false
```

The app uses feet for user-entered and displayed dimensions, converting to meters
for the solver. It opens with an area-based automatic room recommendation. Accept
it or switch to **Custom Room Requirements**, edit the room table and
relationships, then select **Generate test-fit**.

## How the layout works

- Site, room, parking, and staircase dimensions are entered in feet. The existing
  CP-SAT model continues to use meters discretized to a 1 cm grid.
- The rule-based room recommendation considers buildable area after preliminary
  setbacks, floor count, parking, and staircase allowance. It is an estimate and
  can produce a warning when the suggested rooms may not fit.
- Custom room sizes are fixed-size, axis-aligned rectangles; rotation and
  automatic room resizing are not enabled. Optional rooms are omitted only when
  the full requested program is infeasible and a required-only solution works;
  omitted names are shown in the results.
- The solver supports one to five floors. Rooms and the shared staircase shaft
  stay inside the setback-defined buildable rectangle. Parking stays inside the
  site, avoids rooms and the stair, and is optimized toward the selected road side.
- ATTACHED and ADJACENT relationships are hard constraints: the pair must share
  a horizontal or vertical boundary over a positive-length segment. A gap or
  corner-only contact does not satisfy the relationship.
- NEAR and PREFERRED are soft relationships and never restrict feasibility.
  NEAR minimizes the minimum rectilinear gap between the rectangles. PREFERRED
  minimizes only the portion of that gap beyond 1.0 m (about 3.3 ft).
- STACKED remains a soft preference for adjacent-floor room alignment.
- The solver optimizes in priority order: occupied bounding-box area and
  dimensions, total NEAR distance, total PREFERRED excess distance, then
  STACKED alignment, parking near the road side, and lower-left placement.
- The results show site/buildable/open areas, room and stair areas, floor metrics,
  relationships, and actual solver coordinates rendered in feet.
- Floor plans show the site and buildable boundaries, rooms, parking, the
  staircase, gates, a deterministic main-door marker, and conceptual door
  symbols on shared room edges. Pedestrian and driveway paths are conceptual
  and are not validated for conflicts.

This is a preliminary planning prototype, not a construction drawing or
code-certified design. It does not verify local regulations, structural design,
door swings, full circulation, fire safety, or vehicle turning paths. Review
plans with a qualified architect.

## Run tests

```bash
python -m unittest discover -s tests -v
```