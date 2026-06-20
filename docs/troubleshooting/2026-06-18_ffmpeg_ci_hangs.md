# ffmpeg CI install hangs

Subject: the `Install ffmpeg` step in `.github/workflows/test.yml` regularly spends 10-18 minutes
and can remain in progress far longer, stretching total CI latency well past the pytest job it
exists to support.

## Symptom

The `Install ffmpeg` step stalls during `apt-get update` / `apt-get install`. Step logs show
repeated `Ign:` lines against `http://azure.archive.ubuntu.com/ubuntu` before package fetches
eventually continue, consistent with a slow or unresponsive Azure apt mirror rather than a problem
in the package set itself.

## Investigation

- Confirmed the delay sits in apt package downloads from `http://azure.archive.ubuntu.com/ubuntu`,
  not in dpkg unpack or any post-install step.
- The workflow had no explicit `timeout-minutes` on the step and passed no apt retry or HTTP/HTTPS
  timeout options, so a transient mirror stall could wedge the run until the broader GitHub Actions
  job timeout instead of failing fast.
- ffmpeg bundles `ffprobe`; both binaries come from the single `ffmpeg` package, so no extra package
  is required.

## Mitigation implemented

Hardened the existing apt-based install in `.github/workflows/test.yml` without changing CI
structure:

- Added `timeout-minutes: 5` to the `Install ffmpeg` step so a stalled apt fetch fails within an
  explicit bound instead of leaving the workflow in progress for hours.
- Passed `Acquire::Retries=3` and `Acquire::http::Timeout=30` / `Acquire::https::Timeout=30` to both
  `apt-get update` and `apt-get install`, so transient fetch failures retry predictably with bounded
  per-connection timeouts rather than relying on apt defaults.
- Kept `--no-install-recommends` on the install, matching the Dockerfile and
  `scripts/setup-cloud.sh`. ffmpeg still provides `ffprobe`, so the test suite's binary dependencies
  are unaffected.

Larger alternatives (a custom CI image with ffmpeg preinstalled, or splitting the ffmpeg integration
tests into a separate job) are intentionally out of scope here and should be tracked separately if
this mitigation proves insufficient.

## Observed CI run after the change

- Pending: record the `Install ffmpeg` step duration and outcome from the first CI run on the PR for
  this change.
