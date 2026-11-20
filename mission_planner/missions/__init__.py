"""
Drone mission planning: cameras, survey flight lines and (later) mission file export.

Pure Python on top of pyproj and GEOS, without Django models: everything here can be tested with
numbers. Formulas and conventions were checked against mission files exported by DJI Pilot 2
(see tests/test_mission_planning.py).
"""
