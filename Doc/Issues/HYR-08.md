# HYR-08: Untracked junk files and missing .gitignore entries

- **Severity:** Low
- **Status:** Open
- **Component:** repository hygiene

## Impact
`git status` is cluttered, and there is a risk of accidentally committing logs,
editor backups or session files.

## Description
Untracked files currently include `.claude.session`, `README.org.md`,
`config/maintenance_config.yaml~`, `openclaw-2026-09-05.log`,
`openclaw-workspace/AGENTS.md~`, `openclaw-workspace/SOUL.md`,
`openclaw-workspace/USER.md`, `Doc/improvements.md`, and editor lock files such
as `Doc/.~lock.*#`. Some are intentional work in progress (`Doc/improvements.md`,
the workspace files) and need a decision rather than an ignore rule.

## Proposed fix
Add to `.gitignore`: `*~`, `.~lock.*#`, `.claude.session`, `openclaw-*.log`.
Decide separately whether `README.org.md`, `Doc/improvements.md` and the
`openclaw-workspace/` files should be committed or removed.

## Acceptance
`git status` shows only files that are deliberately pending.
