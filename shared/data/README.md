# Test data

Small virus FASTQ for fast agent iteration. The data itself is **git-ignored** — regenerate it
with the fetch script.

## Regenerate

```bash
bash shared/data/fetch_virus_fastq.sh                 # default: SRR11140744, 10k reads
bash shared/data/fetch_virus_fastq.sh <ACCESSION> <N> # any ENA run, N reads
```

## Default dataset

| Field | Value |
|---|---|
| Accession | `SRR11140744` |
| Organism | Severe acute respiratory syndrome coronavirus 2 (SARS-CoV-2) |
| Platform | Illumina |
| Source | ENA (`ftp.sra.ebi.ac.uk`), file `SRR11140744_1.fastq.gz` |
| Subsample | first 10,000 reads (`gzip -dc | head -n 40000 | gzip`) |
| Output | `shared/data/SRR11140744_10k.fastq.gz` |

The subsample is a head-slice, not a random sample — fine for a QC smoke test, not for anything
statistical. Read length is ~100–251 bp (variable), Phred+33.
