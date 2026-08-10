#!/usr/bin/env bash
# Download a small reference genome FASTA for alignment. Default: SARS-CoV-2 (NC_045512.2, ~30 KB),
# the RefSeq that matches the SRR11140744 reads fetched by fetch_virus_fastq.sh.
#
# Usage:
#   bash fetch_reference.sh [ACCESSION]
# Produces:
#   shared/data/<ACCESSION>.fasta   (+ prints the path)
set -euo pipefail

ACC="${1:-NC_045512.2}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT="${HERE}/${ACC}.fasta"

echo ">> Fetching ${ACC} from NCBI ..."
URL="https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=nucleotide&id=${ACC}&rettype=fasta&retmode=text"
curl -fsS "${URL}" -o "${OUT}"

# sanity: first line is a FASTA header, and there is sequence
if [ ! -s "${OUT}" ] || [ "$(head -c1 "${OUT}")" != ">" ]; then
  echo "!! Download did not look like FASTA — check the accession ${ACC}"; rm -f "${OUT}"; exit 1
fi
BP=$(grep -v '^>' "${OUT}" | tr -d '\n' | wc -c | tr -d ' ')
echo ">> Done. ${ACC}: ${BP} bp -> ${OUT}"
echo "${OUT}"
