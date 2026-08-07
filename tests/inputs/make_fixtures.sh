#!/usr/bin/env bash
# Generate the tiny FASTQ fixtures used by tests/run_tests.py. Each triggers a specific harness path.
# Fixtures are small enough to commit. Re-run any time to regenerate.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="${HERE}/../../shared/data/SRR11140744_10k.fastq.gz"

# good.fastq.gz — a real (subsampled) FASTQ that passes preconditions -> run -> evaluation
if [ -f "${SRC}" ]; then
  set +o pipefail                       # head closes the pipe early (SIGPIPE) — expected
  gzip -dc "${SRC}" | head -n 8000 | gzip > "${HERE}/good.fastq.gz"   # 2000 reads
  set -o pipefail
else
  echo "!! ${SRC} not found — run shared/data/fetch_virus_fastq.sh first" >&2
  exit 1
fi

# not_fastq.txt.gz — not FASTQ at all -> onboarding probe -> judgment precondition BLOCK (refuse)
printf 'this is not a fastq file\njust some text\nno @ or + records here\n' | gzip > "${HERE}/not_fastq.txt.gz"

# empty.fastq.gz — zero reads -> precondition BLOCK (refuse)
printf '' | gzip > "${HERE}/empty.fastq.gz"

# badqual.fastq.gz — valid FASTQ structure but garbage quality -> run -> evaluation ANOMALY
python3 - "${HERE}/badqual.fastq.gz" <<'PY'
import gzip, sys
recs = "".join(f"@r{i}\nACGTACGTAC\n+\n##########\n" for i in range(200))  # Phred ~2 -> low quality
with gzip.open(sys.argv[1], "wt") as fh:
    fh.write(recs)
PY

echo "Fixtures written to ${HERE}:"
ls -1 "${HERE}"/*.gz
