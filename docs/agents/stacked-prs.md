# Stacked PRs

We prefer stacked PRs for incremental work: small, reviewable layers
instead of one large PR. Each layer is one dependent concern, bottom
to top, with its own PR based on the branch below it.

## Tooling

- `gh stack` CLI extension (`github/gh-stack`, v0.3.0): `gh extension
  install github/gh-stack`
- Agent skill: `/gh-stack` (`.agents/skills/gh-stack/`, installed with
  `gh skill install github/gh-stack`)
- Git config set by the setup: `rerere.enabled=true`,
  `remote.pushDefault=origin`

## Core loop

```sh
gh stack init <first-layer>     # create stack, or adopt existing branches
# implement one concern, commit
gh stack add <next-layer>       # next layer, branched from the current one
# implement the next concern, commit
gh stack submit --auto          # push every branch, open draft PRs
gh stack view --json            # confirm the stack
```

## Rules

- Create the stack before writing files; do not implement every
  concern on trunk and split it later.
- Edit a layer by checking out the branch that owns the change, then
  `gh stack rebase --upstack` and return to the top.
- Keep the stack linear: one parent, at most one child. Use separate
  stacks for parallel work.
- In non-interactive use, always pass the flags the `/gh-stack` skill
  lists (`gh stack view --json`, `gh stack submit --auto`, never bare
  `gh stack submit` / `gh stack view` — they open a TUI under a PTY).
- Merge with `gh stack merge <PR number> --yes`, never plain
  `gh pr merge`, which cannot merge a stack.
