# Throwaway container for Track B: model-written code runs here, not on your machine.
# The runner starts as root and runs model code as the unprivileged user amp-sandbox (fixed uid 64123, so it never
# matches the uid that owns your files on the host). That user cannot read the runner's environment (API key),
# root-only files, or other runs. Keep the answer key away from it before mounting:
#   chmod -R go-rwx kit/sealed
#   docker build -t amp-runner .
#   docker run --rm -e ANTHROPIC_API_KEY -v "$PWD/..:/amp" amp-runner \
#       python /amp/runner/amp_runner.py --kit /amp/kit --runs /amp/runs_api --config /amp/runner/providers.json
# The runner probes what model code could read before the first run and refuses if anything secret is readable.
FROM python:3.12-slim
RUN pip install --no-cache-dir numpy scipy sympy networkx
RUN useradd -M -u 64123 -s /usr/sbin/nologin amp-sandbox
ENV AMP_SANDBOX_USER=amp-sandbox
WORKDIR /amp
