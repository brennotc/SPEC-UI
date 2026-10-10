---
id: db_easy_001
benchmark_name: DesignBench
complexity: Easy
multimodal: true
# image_path: path/to/image.png   # optional: overrides collocated image auto-detection
# If image_path is omitted, the loader looks for a file named <this_file>.{png,jpg,jpeg,webp}
# in the same directory.  E.g. db_easy_001.png alongside db_easy_001.md
---
## Prompt

Short, vague description of the task with no technical specification.
The model receives only this text (plus the reference image when multimodal=true).

## Specification

Detailed requirements with all explicit constraints, acceptance criteria,
dimensions, colours, typography choices, interaction states, etc.
The model receives this text (plus the reference image) for the With_Spec prompt.
