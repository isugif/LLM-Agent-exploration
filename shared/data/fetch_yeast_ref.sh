#!/usr/bin/env bash
# Fetch the S. cerevisiae R64 reference genome (FASTA) + gene annotation (GTF) from Ensembl.
# Small (~12 Mb genome) — fast to align and QC. Used as the reference/annotation for the yeast
# RNA-seq demo (minimap2 -> samtools sort/markdup -> rustqc rna --gtf).
#
# Usage:  bash fetch_yeast_ref.sh
# Produces:
#   shared/data/Saccharomyces_cerevisiae.R64-1-1.fasta
#   shared/data/Saccharomyces_cerevisiae.R64-1-1.genes.gtf
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REL="release-110"
BASE="https://ftp.ensembl.org/pub/${REL}"
GENOME_URL="${BASE}/fasta/saccharomyces_cerevisiae/dna/Saccharomyces_cerevisiae.R64-1-1.dna.toplevel.fa.gz"
GTF_URL="${BASE}/gtf/saccharomyces_cerevisiae/Saccharomyces_cerevisiae.R64-1-1.110.gtf.gz"
FASTA_OUT="${HERE}/Saccharomyces_cerevisiae.R64-1-1.fasta"
GTF_OUT="${HERE}/Saccharomyces_cerevisiae.R64-1-1.genes.gtf"

echo ">> genome: ${GENOME_URL}"
curl -fsS "${GENOME_URL}" | gzip -dc > "${FASTA_OUT}"
echo ">> gtf:    ${GTF_URL}"
curl -fsS "${GTF_URL}" | gzip -dc > "${GTF_OUT}"

BP=$(grep -v '^>' "${FASTA_OUT}" | tr -d '\n' | wc -c | tr -d ' ')
GENES=$(awk -F'\t' '$3=="gene"' "${GTF_OUT}" | wc -l | tr -d ' ')
echo ">> done. genome ${BP} bp -> ${FASTA_OUT}"
echo ">>       ${GENES} genes -> ${GTF_OUT}"
