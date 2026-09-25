# Manual regression
Project policy must enable regression. An authorized human submits a request through /regressions. Discovery freezes the base candidate, then the human approves the regression plan. Validation uses the same catalog commands, required Journey versions, protected checks and manual-attestation mechanisms as implementation runs.

A regression never invokes the implementation agent, creates a target commit or delivers a PR. Results remain tied to the frozen candidate and produce incidents when review is needed. A new work request is a separate explicit intake action.

Schedules are represented as disabled policy metadata; schemas reject schedules_enabled=true. No background schedule can silently execute a regression. Actual Linux behavior is NOT RUN.
