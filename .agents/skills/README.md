# Agent skills on the gtm-agent branch

Skills installed on this branch, in `.agents/skills/`, with matching
symlinks in `.claude/skills/` (following the repo's existing pattern:
`.claude/skills/<name>` -> `../../.agents/skills/<name>`).

## Sources

- **Matt Pocock — Skills For Real Engineers** (`mattpocock/skills`):
  31 skills from `skills/engineering`, `skills/productivity` and
  `skills/misc`. `skills/in-progress` (8 skills) and `skills/deprecated`
  were NOT copied — they are unfinished / retired upstream.
- **Cursor pstack** (`cursor/plugins`, `pstack/`): all 58 skills from
  `pstack/skills`, including `poteto-mode` and the 22 `principle-*`
  skills. Version 0.15.44 at install time.
- **GitHub gh-stack** (`github/gh-stack`): 1 skill, `gh-stack`, installed
  with `gh skill install github/gh-stack` (v0.3.0). Manages stacked
  PRs with the `gh stack` CLI extension — see `docs/agents/`
  for the stacked-PR workflow used on this branch.
- **Pydantic — official skills** (`pydantic/skills`): 21 skills from the
  top-level `skills/` directory (cross-agent, agentskills.io standard),
  at commit 98f591c. `building-pydantic-ai-agents` and
  `pydantic-ai-harness` for building agents with Pydantic AI, `pydantic`
  for validation, 9 `migrating-*-to-pydantic-ai` skills (LangChain,
  OpenAI Agents SDK, Claude Agent SDK, Google ADK, Mastra, Agno, Pi,
  Vercel AI SDK, Deep Agents), and 8 Logfire skills (setup,
  instrumentation, query, evals, UI, frontend, gateway,
  coding-agents). The `plugins/` copies in that repo were NOT copied —
  they duplicate these skills plus host-specific commands/hooks.

Total: 111 skills (31 + 58 + 1 + 21).

## Name collisions

`teach` and `tdd` exist in both collections. The pstack versions keep
the plain names (`teach`, `tdd`) because `poteto-mode` routes to them.
The Matt Pocock versions were renamed to `matt-teach` and `matt-tdd`,
and their `SKILL.md` frontmatter `name:` was updated to match.

## How to use

- `/poteto-mode` — pstack's default entry point for rigorous work.
- `/setup-pstack` — pick pstack models / reasoning budget.
- `/setup-matt-pocock-skills` — run once per repo: issue tracker,
  triage labels, domain docs layout.
- `/gh-stack` — stacked PRs: create a stack before writing files, one
  dependent concern per layer, submit with `gh stack submit --auto`.
- `/building-pydantic-ai-agents` — the main skill for building agents
  with Pydantic AI in this repo; `/pydantic` for Pydantic validation;
  `/logfire-instrumentation` and `/logfire-query` for observability.
- Everything else is situational: `/tdd`, `/teach`, `/implement`,
  `/code-review`, `/triage`, `/pr`, etc.

## Updating

These are copies, not submodules or plugins — they do not auto-update.
Re-copy from upstream and commit when you want a newer version.
