# Security

## Threat model
Track B (`runner/amp_runner.py`) executes code written by a language model. That code must not be able to read the
API key, the answer key (`kit/sealed/KEYS.json`), or the files of other runs, and it must not be able to forge the
receipts that prove `live` provenance.

## Controls
- **Separate OS user.** With `--sandbox-user` (set by the Docker image as `amp-sandbox`, uid 64123) the runner starts
  as root and runs model code as an unprivileged user. That user cannot read the runner's `/proc/<pid>/environ` or
  memory. Its work folder is handed to it; `runs/` is traversable but not listable, and result files are private.
- **Clean environment.** The sandbox environment is built from scratch (PATH, HOME, locale and public run facts);
  nothing is inherited from the runner.
- **Pre-flight probe.** Before the first run the runner checks, with the sandbox's own credentials, whether the
  runner's environment, any `KEYS.json` under the kit, or any file in `runs/` is readable. A real API run is refused
  if anything is; `--unsafe-shared-uid` overrides this for a disposable machine.
- **Signed receipts.** `#LIVE` outputs are logged by the runner and signed with an HMAC key generated in the runner
  process; the grader accepts `live` provenance only with a valid receipt.
- **Verifier separation.** A cross-check model may not be one of the compared models.

## Operating it safely
Use the Docker image on a disposable host, keep `kit/sealed` unreadable to other users (`chmod -R go-rwx kit/sealed`),
and pass API keys only as environment variables.

## Reporting
Please report security issues privately to the repository owner rather than in a public issue.
