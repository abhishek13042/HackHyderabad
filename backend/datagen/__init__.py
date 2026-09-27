"""Synthetic data generator (SPEC-02).

Builds purchase registers and GSTR-2B files with planted vendor behaviours, plus
the ground truth used by seeding and evals. Nothing in `backend.app` imports
this package, so generator-only facts (like archetypes) can't reach the agent.
"""
