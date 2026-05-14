"""Main release pipeline steps.

The release path is intentionally limited to seven ordered steps:
inspect, pick, export, upload, ifx, handoff, and dcl. Offboard validation is
kept outside this package so it can run independently.
"""
