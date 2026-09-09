# AGENTS.md - OpenClaw Workspace

## Tools

### Local notes (migrated from TOOLS.md)

# TOOLS.md - Local Notes

Skills define _how_ tools work. This file is for _your_ specifics — the stuff that's unique to your setup.

## What Goes Here

Things like:

- Camera names and locations
- SSH hosts and aliases
- Preferred voices for TTS
- Speaker/room names
- Device nicknames
- Anything environment-specific

## Examples

```markdown
### Cameras

- living-room → Main area, 180° wide angle
- front-door → Entrance, motion-triggered

### SSH

- home-server → 192.168.1.100, user: admin

### TTS

- Preferred voice: "Nova" (warm, slightly British)
- Default speaker: Kitchen HomePod
```

## Why Separate?

Skills are shared. Your setup is yours. Keeping them apart means you can update skills without losing your notes, and share skills without leaking your infrastructure.

---

Add whatever helps you do your job. This is your cheat sheet.

### hybrid-rag__ask_documents

This is the tool for anything that might be answered by a fact, record, or detail
specific to the user (account numbers, dates, purchases, anything they've stored).
Always call it for these — it is not a privacy concern, the user has consented to this
collection being searched on their behalf. Never decline or tell the user to look it up
themselves without calling it first.

Call it fresh EVERY time this kind of question comes up, with no exceptions —
including when the exact same question was already asked and answered earlier in this
same conversation. Do not answer from your own memory of a prior turn's answer. Treat
every such question as if you have never seen it before.
