#!/usr/bin/env bash
# Download a small virus FASTQ from ENA and subsample it for fast agent iteration.
#
# Default: SRR11140744 — Severe acute respiratory syndrome coronavirus 2 (SARS-CoV-2),
# Illumina. We pull the first read file and subsample the first N reads so the whole
# pipeline runs in seconds. No sra-tools / seqtk needed — just curl + gzip.
#
# Usage:
#   bash fetch_virus_fastq.sh [ACCESSION] [N_READS]
# Produces:
#   shared/data/<ACCESSION>_<N>k.fastq.gz   (+ prints the path)
set -euo pipefail

ACC="${1:-SRR11140744}"
N_READS="${2:-10000}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT="${HERE}/${ACC}_$((N_READS / 1000))k.fastq.gz"

echo ">> Looking up ${ACC} on ENA ..."
FTP_FIELD=$(curl -fsS "https://www.ebi.ac.uk/ena/portal/api/filereport?accession=${ACC}&result=read_run&fields=fastq_ftp&format=tsv" | tail -n +2)
# fastq_ftp is a ';'-separated list; prefer the _1 (R1) file, else the first entry.
FIRST_URL=$(echo "${FTP_FIELD}" | tr ';' '\n' | grep -E '_1\.fastq\.gz$' | head -1 || true)
[ -z "${FIRST_URL}" ] && FIRST_URL=$(echo "${FTP_FIELD}" | tr ';' '\n' | grep -E '\.fastq\.gz$' | head -1)
[ -z "${FIRST_URL}" ] && { echo "!! No fastq.gz found for ${ACC}"; exit 1; }

TMP="$(mktemp -t fastqdl.XXXXXX.gz)"
trap 'rm -f "${TMP}"' EXIT

echo ">> Downloading https://${FIRST_URL}"
curl -fsS "https://${FIRST_URL}" -o "${TMP}"

echo ">> Subsampling first ${N_READS} reads -> ${OUT}"
# `head` closes the pipe early, sending SIGPIPE to `gzip -dc`; disable pipefail so that
# expected signal doesn't trip `set -e` before we finish writing OUT.
set +o pipefail
gzip -dc "${TMP}" | head -n $((N_READS * 4)) | gzip > "${OUT}"
set -o pipefail

COUNT=$(( $(gzip -dc "${OUT}" | wc -l) / 4 ))
echo ">> Done. ${COUNT} reads written."
echo "${OUT}"
