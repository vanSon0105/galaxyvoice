# Batch and queue workflow

Type: task
Status: open
Blocked by: 02, 03, 05

## Question

How should Galaxy execute, inspect, retry, cancel, and resume a batch of
single-voice, multilingual, or long-form synthesis items without overrunning
available CPU/GPU resources?

## Done when

The Batch contract covers JSONL/import, per-item overrides, combined output,
progress, partial success, retry, and a portable batch manifest.
