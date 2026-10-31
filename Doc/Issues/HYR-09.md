# HYR-09: Read-only log account `ragr` on npabot-u24 can run arbitrary commands

- **Severity:** Low-Medium (limited by account privileges; exposure grows if the key leaks)
- **Status:** Open (partially mitigated)
- **Component:** `ragr@npabot-u24` (192.168.1.29), `/home/ragr/.ssh/authorized_keys`; used by the
  planned tool-call monitor (`Doc/step-9-requirements.md` §7, option A)

## Impact
The key used to read OpenClaw logs also permits running any command as `ragr`. Anyone
holding the private key and connecting from the allowed address (the desktop) can run
commands such as `id` or read any file that `ragr` can read on the VM. `ragr` has no sudo,
is in no extra groups, cannot read `/home/nick` or `~/.openclaw/openclaw.json`, and has
only read access to `/tmp/openclaw/`, so the damage is limited to reading world-readable
files and the OpenClaw logs (which contain a Signal phone number). If the key leaks to a
machine that can spoof or take over 192.168.1.53, the same applies there.

## Description
Verified on 2026-10-30:
- In place: `from="192.168.1.53"`, `no-port-forwarding`, `no-agent-forwarding`,
  `no-X11-forwarding`, `no-pty`. Forwarding and interactive shells are refused.
  `authorized_keys` is mode 600; home is 750; sudo needs a password.
- Not in place: **no forced `command=`**, so arbitrary non-interactive commands and
  `sftp` both work. The login shell is `/bin/bash`.
- The key is the same public key as `nick`'s `claude@npalmass-desk1` key, so a leak
  exposes both accounts and neither can be revoked alone.
- Not verified (cannot be seen from `ragr`): VM `sshd` settings such as `AllowUsers`, and
  whether the firewall limits port 22 to the LAN.

## Proposed fix
1. Add a forced command to the key, for example
   `restrict,from="192.168.1.53",command="/usr/local/bin/ragr-fetch" ssh-ed25519 …`.
   `ragr-fetch` allows only read operations: list `/tmp/openclaw` and print a file whose
   name matches `^openclaw-(dev-)?[0-9]{4}-[0-9]{2}-[0-9]{2}\.log$` (no `/`, no `..`). It
   reads `$SSH_ORIGINAL_COMMAND` and rejects everything else. Alternatively use
   `internal-sftp` with a chroot-like restriction, but the wrapper is simpler.
2. Generate a separate key pair for `ragr` (desktop side, passphrase-less file readable only
   by the monitor's user), and remove the shared key from `ragr`'s `authorized_keys`.
3. Set the login shell to `/usr/sbin/nologin` once the forced command is in place (it still
   runs the forced command; check that it works with the chosen wrapper), or keep
   `/bin/bash` only if the wrapper needs it.
4. On the VM, check `sshd -T` for `AllowUsers`/`PasswordAuthentication`, and confirm the
   firewall (`ufw status`) limits port 22 to 192.168.1.0/24.
5. Re-run the checks listed under Acceptance after the change.

## Acceptance
- `ssh ragr@npabot-u24 id` is refused or returns the wrapper's rejection message.
- `ssh ragr@npabot-u24 <log file name>` returns that day's log.
- A path such as `../../etc/passwd` or `openclaw-2026-10-30.log; id` is rejected.
- `ragr` uses its own key; the `nick` key no longer logs in as `ragr`.
- Documented in `Doc/step-9-requirements.md` §7.

## Related
- `Doc/step-9-requirements.md` §6 (privacy) and §7 (tool-call data path).
- The read ACLs on `/tmp/openclaw` were set by the user on 2026-10-30; the logs are in
  `/tmp`, so history is lost on reboot (retention is handled by the pull job, not this
  ticket).
