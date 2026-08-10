# Test data

Small, real datasets for fast agent iteration. **All data here is git-ignored** — only the fetch
scripts are tracked. Regenerate anything with the scripts below.

Subsamples are `head`-slices (first N reads), not random samples — fine for QC / mechanical
pipeline testing, not for anything statistical.

## Fetch scripts

```bash
bash shared/data/fetch_virus_fastq.sh              # SARS-CoV-2 reads (single sample)
bash shared/data/fetch_reference.sh                # SARS-CoV-2 reference genome (FASTA)
bash shared/data/fetch_rnaseq.sh                   # yeast RNA-seq, 3 WT + 3 snf2Δ replicates
bash shared/data/fetch_yeast_ref.sh                # yeast genome (FASTA) + annotation (GTF)
```

Each script takes optional args (see its header) — e.g. a different ENA accession, read count, or
replicate list.

## 1. SARS-CoV-2 — reads + reference (used by: fastqc, minimap2)

| File | What | Source |
|---|---|---|
| `SRR11140744_10k.fastq.gz` | 10k Illumina reads, SARS-CoV-2 | ENA run `SRR11140744` |
| `NC_045512.2.fasta` | reference genome (29,903 bp, Wuhan-Hu-1) | NCBI RefSeq `NC_045512.2` |

`fetch_virus_fastq.sh [ACCESSION] [N]` · `fetch_reference.sh [ACCESSION]`. Read length ~100–251 bp
(variable), Phred+33.

## 2. Yeast RNA-seq — replicated treatment vs control (used by: minimap2, samtools_sort/markdup, rustqc)

*S. cerevisiae* SNF2 study (ENA `PRJEB5348`): wild-type vs snf2Δ, single-end 50 bp. Single-end means
`samtools markdup` needs no `fixmate` step. Three **distinct biological replicates** per condition
(one lane each; the study has 7 lanes/sample — deduplicated to distinct `sample_alias`).

| File | Condition | ENA sample | Accession |
|---|---|---|---|
| `wt1_ERR458493_10k.fastq.gz` | control (WT) | wt_sample1 | `ERR458493` |
| `wt2_ERR458494_10k.fastq.gz` | control (WT) | wt_sample2 | `ERR458494` |
| `wt3_ERR458495_10k.fastq.gz` | control (WT) | wt_sample3 | `ERR458495` |
| `snf2_1_ERR458500_10k.fastq.gz` | treatment (snf2Δ) | mu_sample1 | `ERR458500` |
| `snf2_2_ERR458501_10k.fastq.gz` | treatment (snf2Δ) | mu_sample2 | `ERR458501` |
| `snf2_3_ERR458502_10k.fastq.gz` | treatment (snf2Δ) | mu_sample3 | `ERR458502` |

Reference + annotation (Ensembl R64, release-110):

| File | What |
|---|---|
| `Saccharomyces_cerevisiae.R64-1-1.fasta` | genome (~12 Mb) |
| `Saccharomyces_cerevisiae.R64-1-1.genes.gtf` | gene annotation (GTF) |

`fetch_rnaseq.sh ["CTRL_ACCS"] ["TREAT_ACCS"] [N]` — each list is space-separated ENA run
accessions; it streams the download and stops after N reads. `fetch_yeast_ref.sh` pulls the
genome + GTF.

## RNA-seq QC chain

The yeast set is set up for the alignment-QC path: align each sample, sort + mark duplicates, then
QC — rustqc requires a coordinate-sorted, duplicate-marked BAM plus the GTF.

```bash
minimap2 -ax sr Saccharomyces_cerevisiae.R64-1-1.fasta wt1_ERR458493_10k.fastq.gz \
  | samtools sort -o wt1.sorted.bam -
samtools markdup wt1.sorted.bam wt1.markdup.bam
rustqc rna --gtf Saccharomyces_cerevisiae.R64-1-1.genes.gtf -j summary.json wt1.markdup.bam
```

In the app the same runs through the four harnesses via `samtools_sort` → `samtools_markdup` →
`rustqc` (each a routable tool; rustqc refuses a raw/unsorted BAM with the exact fix). The 3-vs-3
design is there for a later differential-expression step.
