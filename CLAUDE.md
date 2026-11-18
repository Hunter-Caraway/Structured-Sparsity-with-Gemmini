@AGENTS.md

# Claude Code: coordinator workflow

## Role
- The main session is the coordinator ("general"): delegate, monitor, report. Do not do fixes, builds or runs
  inline; spawn a scoped agent for each issue as it is found.
- Report to the user tersely: what finished, results with log paths, what is running, what needs a decision.

## Spawning agents
- Default: `model: sonnet`, `effort: medium`, unless the user asks otherwise.
- Give each agent: a scoped file set (no two agents edit the same file), a server simulation quota (total 12),
  its worklog path, the hard rules from AGENTS.md, and the 50-line report limit.
- Pass findings between agents (e.g. investigation results to the agent doing the fix).
- Stop agents that idle-loop or hang; their worklog's `RESUME HERE` is the hand-off.

## Monitoring
- Watch long server runs with a background wait on the run's `STATUS` file, not a tight poll.
- Filters must catch failures (assert, timeout, unverified output), not only successes. Expected asserts from
  NEG tests are not failures.
- Copy anything worth keeping out of the session scratchpad into the project before the session ends.

## Offline windows
- The user works in set windows (2026-11-12 13:00-17:00, 2026-11-13 19:00-24:00 EST) and is offline between them:
  no VPN, so the SSH socket dies.
- About 30 minutes before a window ends: have every agent checkpoint (`RESUME HERE`), leave only `nohup` server
  jobs running, and give the user the reconnect steps:
  1. `! sudo -E gpclient connect --browser default vpn.floridapoly.edu`
  2. `! ssh -o ControlMaster=yes -o ControlPath=/tmp/claude-1000/cm-%C -o ControlPersist=12h -fN ai-user@ai-1769.floridapoly.org`
- On "resume": relaunch work streams from their worklogs.
