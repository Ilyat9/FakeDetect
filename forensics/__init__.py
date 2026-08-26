"""Forensic pre-LLM layers (Block B): perceptual hashing, ELA, EXIF analysis.

These are cheap CPU-only signals computed BEFORE any LLM call:
- pHash short-circuits repeated/identical images (no LLM spend),
- ELA gives an objective tampering signal usable as evidence,
- EXIF inconsistencies add red flags to the indicator list.
"""
