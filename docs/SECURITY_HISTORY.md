# Security history

This is the record of an earlier credential exposure. It happened in a retired
prototype repository, not in this one. Current controls and limitations are in
[security and privacy](SECURITY_PRIVACY.md).

## The retired prototype

An earlier prototype repository, public for a period under a different name, had
committed archives containing OpenAI and ElevenLabs API keys, along with demo
appointment records and audio from a retired voice version. A review at the time noted
that the appointment records held patient-like names, contact details and visit
reasons of uncertain provenance (see the retained
[risk register extract](history/security/M0_RISK_REGISTER.md)). Separately, the owner
states that the legacy data was synthetic demo material. This record does not resolve
the two: the provenance finding stands as recorded, and the owner's statement is not
verified here. That repository's contents were not re-examined.

## This repository

This repository starts from a clean root commit (`6521b87`, 2026-10-16), built from a
reviewed file allowlist. No commits, archives, audio or appointment records from the
prototype were carried over.

### Supported by repository inspection

| Check | Scope | Date | Result |
| --- | --- | --- | --- |
| gitleaks 8.30.1 | Every ref at the time | Recorded 2026-10-30; the scan's exact date and the commits it covered were not recorded | No findings |
| gitleaks 8.30.1 (`gitleaks git --log-opts=--all --redact`) | One local clone's branches, remote-tracking refs and stash: 71 commits | 2026-11-05 | No findings |
| Blob inspection (`git rev-list --objects --all`) | The same refs: 505 blobs | 2026-11-05 | No blob contains a NUL byte, so none is audio, an archive or another binary file; the only env-named file is `.env.example` |

These are dated snapshots. Each covers only the commits reachable from those refs when
it ran: not GitHub pull-request refs that were never fetched, and not later commits.
Later commits are checked on every push by the current-tree check in
[`scripts/check_synthetic.py`](../scripts/check_synthetic.py), which does not scan
history, until history is scanned again.

### Reported by the owner

These are the owner's statements. The repository holds no evidence for them, and no
credential was tested by this project.

- The exposed OpenAI and ElevenLabs keys were revoked and rotated (reported on
  2026-10-13).
- Provider usage for the exposure window was reviewed with no unexpected activity.
- The legacy repository was deleted; an authenticated request to it later returned
  HTTP 404.

## What this does not establish

Rebuilding from a clean root and deleting the legacy repository remove the prototype's
content from repositories the owner controls. They do not show that copies made while
it was public are gone: forks, clones, caches, mirrors or secret-scanning datasets may
still hold the archives, records and audio. For the keys, the remedy is that they were
revoked and rotated, not that they were deleted.

## Conclusion

Within the scans above, this repository's history contains no credentials, archives or
audio, and the owner reports that the exposed keys were revoked and rotated. Copies of
the retired prototype outside the owner's control are not covered by either.
