# pstack model configuration — adapted for agent skills (Muse / .agents)

This is the agent-skills adaptation of the pstack setup rule. The
Cursor/Claude Code version lives at `~/.cursor/rules/pstack-models.mdc`
(written by `/setup-pstack`); this file carries the same choices into
the repo, so any agent reading `.agents/skills/` — including Muse —
can apply them without Cursor.

- Budget: `large` (xhigh reasoning)
- Defaults: pstack defaults v3 (`# defaults: 3`)
- Models: no Claude/Gemini/Grok model slugs could be detected in Muse,
  and `/setup-pstack` never writes a real slug that was not confirmed
  available. Every role therefore uses `inherit-parent`, meaning the
  role runs on the parent session model. Re-run `/setup-pstack` in
  Cursor/Claude Code with your slugs to replace these with real models.

| Role | Model |
| --- | --- |
| feature, refactoring | inherit-parent |
| bug-fix | inherit-parent |
| perf-issue | inherit-parent |
| hillclimb | inherit-parent |
| judgment and prose | inherit-parent |
| arena runners | inherit-parent |
| arena cross-judge pool | inherit-parent |
| swarm workers | inherit-parent |
| interrogate reviewers | inherit-parent |

`inherit-parent` / `auto` means: omit the `model` on a subagent spawn
and use the parent chat model. In a panel role the list length sets the
fan-out; a single `inherit-parent` entry means one runner/reviewer on
the parent model. An `inherit-parent` value never judges in
`arena cross-judge pool`.
