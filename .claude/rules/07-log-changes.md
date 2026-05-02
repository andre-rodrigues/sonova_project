# Rule File: Rules for change logging.

> Explains how changes in the code base should be logged in `CHANGELOG.md`. This file is loaded by Claude Code as a standing rule set.
> These rules are **non-negotiable** for this project. Any deviation requires an explicit note in CHANGELOG.md explaining why.

---

## Rules (Non-Negotiable)

1. **Append only** — never delete, edit, or rewrite any existing entry. Write to the end of the file only.
2. Every session that modifies code **must** add an entry before closing
3. Format: `## [YYYY-MM-DD] — <title>` followed by relevant sections
4. Reference DQ rule IDs (DQ-01 through DQ-25), layer names, and table names exactly as
   defined in CLAUDE.md
5. Note any deviation from CLAUDE.md specs and the reason why
