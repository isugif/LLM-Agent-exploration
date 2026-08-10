#!/usr/bin/env bash
# Fetch a small REPLICATED RNA-seq treatment-vs-control set from ENA and subsample each sample.
#
# Default: the S. cerevisiae SNF2 study (PRJEB5348) — wild-type vs snf2Δ, single-end 50 bp, 3
# biological replicates each (distinct samples, verified via ENA sample_alias: wt_sample*/mu_sample*).
# Single-end means samtools markdup needs no `fixmate` step. One lane per biological replicate.
#
# Usage:
#   bash fetch_rnaseq.sh ["CTRL_ACCS"] ["TREAT_ACCS"] [N_READS]
#   (each *_ACCS is a space-separated list of ENA run accessions)
# Produces (condition-labelled, self-documenting):
#   shared/data/wt<i>_<ACC>_<N>k.fastq.gz   and   shared/data/snf2_<i>_<ACC>_<N>k.fastq.gz
set -euo pipefail

CTRL_ACCS="${1:-ERR458493 ERR458494 ERR458495}"   # wt_sample1/2/3  (wild type)
TREAT_ACCS="${2:-ERR458500 ERR458501 ERR458502}"  # mu_sample1/2/3  (snf2Δ mutant)
N_READS="${3:-10000}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

fetch_one() {  # <accession> <label>
  local ACC="$1" LABEL="$2" OUT FTP FIRST TMP
  OUT="${HERE}/${LABEL}_${ACC}_$((N_READS / 1000))k.fastq.gz"
  echo ">> ${LABEL} (${ACC}): looking up on ENA ..."
  FTP=$(curl -fsS "https://www.ebi.ac.uk/ena/portal/api/filereport?accession=${ACC}&result=read_run&fields=fastq_ftp&format=tsv" | tail -n +2 | awk -F '\t' '{print $NF}')
  FIRST=$(echo "${FTP}" | tr ';' '\n' | grep -E '\.fastq\.gz$' | head -1 || true)
  [ -z "${FIRST}" ] && { echo "!! no fastq.gz for ${ACC} (try a different accession)"; return 1; }
  # stream + stop early: head closes the pipe once N reads are in, so curl only downloads a few MB
  # (not the whole lane file). pipefail off so the expected SIGPIPE doesn't trip `set -e`.
  set +o pipefail
  curl -fsS "https://${FIRST}" | gzip -dc | head -n $((N_READS * 4)) | gzip > "${OUT}"
  set -o pipefail
  echo ">> wrote ${OUT}"
}

i=1; for acc in ${CTRL_ACCS};  do fetch_one "${acc}" "wt${i}";    i=$((i + 1)); done
i=1; for acc in ${TREAT_ACCS}; do fetch_one "${acc}" "snf2_${i}"; i=$((i + 1)); done
echo ">> done: $(echo ${CTRL_ACCS} | wc -w | tr -d ' ') control + $(echo ${TREAT_ACCS} | wc -w | tr -d ' ') treatment replicates."
