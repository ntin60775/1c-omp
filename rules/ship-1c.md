---
description: Opt-in rule for 1C projects — /ship always stops before commit for human diff review. Enable only in a 1C project.
alwaysApply: true
---

# 1C project: review before commit

**Opt-in.** Enable this rule only in a 1C project (set `alwaysApply: true` there). When
active, `/ship` runs with `stop-before-commit`: implement, tests and independent review
run automatically; commit and everything after (MR, dev, prod, merge, deploy) wait for
the operator's explicit "continue".
