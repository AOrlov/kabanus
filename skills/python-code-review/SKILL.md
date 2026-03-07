---
name: python-code-review
description: Perform rigorous Python code reviews focused on correctness, edge-case bugs, security risks, performance issues, maintainability, Python best practices, and test coverage. Use when a user asks to review Python code, a patch, a pull request, or files and expects findings prioritized by severity with concrete fixes.
---

# Python Code Review

Review Python code with a findings-first mindset.

## Review Focus

- Validate correctness and edge-case handling.
- Identify security risks, including unsafe input handling, secrets exposure, injection vectors, and unsafe deserialization.
- Detect performance issues, including unnecessary I/O, repeated work, and avoidable allocations.
- Evaluate readability and maintainability: naming, structure, cohesion, duplication, and complexity.
- Apply Python best practices: PEP 8, typing, exception handling, resource management, and appropriate use of dataclasses.
- Assess test quality and point out missing or weak coverage.

## Review Workflow

1. Read the target code and related tests before judging implementation details.
2. Prioritize behavior-impacting defects over style nits.
3. Validate claims against specific code locations.
4. Propose concrete fixes, including corrected snippets when useful.
5. Call out assumptions when context is missing.

## Response Format

1. List findings first, ordered by severity: Critical, High, Medium, Low.
2. For each finding, include:
   - file path and line number (if available),
   - why it is a problem,
   - a concrete fix.
3. List assumptions or open questions.
4. End with a short summary of overall code quality.

If no important issues are found, explicitly say: `No significant issues found`, then list residual risks or testing gaps.
