# 0206 to 0508 Three-Class Experiments

This directory preserves the analysis and job scripts used to improve the
0206-trained RA triage model on the 0508 evaluation set.

Start with [HANDOFF.md](HANDOFF.md). It records the experiment constraints,
completed analyses, current best result, rejected directions, and pending
upsampling jobs.

## Contents

- `HANDOFF.md`: experiment status and reproducibility notes.
- `_*.py`: dataset construction, rescoring, ceiling, consistency, and error
  attribution analyses.
- `_*.sh`: remote training, validation sweep, and Axe submission entry points.

Most scripts reference datasets and experiment outputs under `~/ofs` or NFS.
They are retained as reproducibility assets and are not part of the
`check_sim` road/simulation bag workflow.
