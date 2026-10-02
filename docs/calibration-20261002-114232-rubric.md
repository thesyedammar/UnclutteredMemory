# Calibration 20261002-114232 (rubric, jev-1.13)

Prompt style: rubric. Model: jev-1.13 (only model, no fallback).
Stub scoring is pinned by the frozen golden labels; calibration
tunes the live prompts only (see eval/GOLDEN_CHANGELOG.md).
INFORMATION ONLY: agreement rates gate nothing.

- admit      stub-vs-live 40/56 = 71.4%; live-vs-label 40/56 = 71.4%
- importance stub-vs-live 20/24 = 83.3%; live-vs-label 20/24 = 83.3%

## admit per-case (stub vs live vs label)
- g-admit-0001 stub='STORE' live='STORE' label='STORE' agree
- g-admit-0002 stub='STORE' live='STORE' label='STORE' agree
- g-admit-0003 stub='STORE' live='STORE' label='STORE' agree
- g-admit-0004 stub='STORE' live='STORE' label='STORE' agree
- g-admit-0005 stub='STORE' live='STORE' label='STORE' agree
- g-admit-0006 stub='STORE' live='STORE' label='STORE' agree
- g-admit-0007 stub='STORE' live='STORE' label='STORE' agree
- g-admit-0008 stub='STORE' live='STORE' label='STORE' agree
- g-admit-0009 stub='STORE' live='STORE' label='STORE' agree
- g-admit-0010 stub='STORE' live='STORE' label='STORE' agree
- g-admit-0011 stub='STORE' live='STORE' label='STORE' agree
- g-admit-0012 stub='STORE' live='STORE' label='STORE' agree
- g-admit-0013 stub='STORE' live='STORE' label='STORE' agree
- g-admit-0014 stub='STORE' live='STORE' label='STORE' agree
- g-admit-0015 stub='STORE' live='DROP' label='STORE' differ
- g-admit-0016 stub='STORE' live='STORE' label='STORE' agree
- g-admit-0017 stub='STORE' live='STORE' label='STORE' agree
- g-admit-0018 stub='STORE' live='DROP' label='STORE' differ
- g-admit-0019 stub='STORE' live='DROP' label='STORE' differ
- g-admit-0020 stub='STORE' live='DROP' label='STORE' differ
- g-admit-0021 stub='STORE' live='STORE' label='STORE' agree
- g-admit-0022 stub='STORE' live='STORE' label='STORE' agree
- g-admit-0023 stub='STORE' live='STORE' label='STORE' agree
- g-admit-0024 stub='STORE' live='STORE' label='STORE' agree
- g-admit-0025 stub='DROP' live='DROP' label='DROP' agree
- g-admit-0026 stub='DROP' live='DROP' label='DROP' agree
- g-admit-0027 stub='DROP' live='DROP' label='DROP' agree
- g-admit-0028 stub='DROP' live='DROP' label='DROP' agree
- g-admit-0029 stub='DROP' live='DROP' label='DROP' agree
- g-admit-0030 stub='DROP' live='DROP' label='DROP' agree
- g-admit-0031 stub='DROP' live='DROP' label='DROP' agree
- g-admit-0032 stub='DROP' live='DROP' label='DROP' agree
- g-admit-0033 stub='DROP' live='DROP' label='DROP' agree
- g-admit-0034 stub='DROP' live='DROP' label='DROP' agree
- g-admit-0035 stub='DROP' live='DROP' label='DROP' agree
- g-admit-0036 stub='DROP' live='DROP' label='DROP' agree
- g-admit-0037 stub='DROP' live='QUARANTINE' label='DROP' differ
- g-admit-0038 stub='DROP' live='DROP' label='DROP' agree
- g-admit-0039 stub='DROP' live='DROP' label='DROP' agree
- g-admit-0040 stub='DROP' live='DROP' label='DROP' agree
- g-admit-0041 stub='DROP' live='STORE' label='DROP' differ
- g-admit-0042 stub='DROP' live='DROP' label='DROP' agree
- g-admit-0043 stub='DROP' live='DROP' label='DROP' agree
- g-admit-0044 stub='DROP' live='DROP' label='DROP' agree
- g-admit-0045 stub='DROP' live='DROP' label='DROP' agree
- g-admit-0046 stub='DROP' live='DROP' label='DROP' agree
- g-admit-0047 stub='QUARANTINE' live='STORE' label='QUARANTINE' differ
- g-admit-0048 stub='QUARANTINE' live='DROP' label='QUARANTINE' differ
- g-admit-0049 stub='QUARANTINE' live='STORE' label='QUARANTINE' differ
- g-admit-0050 stub='QUARANTINE' live='DROP' label='QUARANTINE' differ
- g-admit-0051 stub='QUARANTINE' live='DROP' label='QUARANTINE' differ
- g-admit-0052 stub='QUARANTINE' live='DROP' label='QUARANTINE' differ
- g-admit-0053 stub='QUARANTINE' live='DROP' label='QUARANTINE' differ
- g-admit-0054 stub='QUARANTINE' live='STORE' label='QUARANTINE' differ
- g-admit-0055 stub='QUARANTINE' live='DROP' label='QUARANTINE' differ
- g-admit-0056 stub='QUARANTINE' live='STORE' label='QUARANTINE' differ

## importance per-case (stub vs live vs label)
- g-importance-0001 stub=5 live=5 label=5 agree
- g-importance-0002 stub=5 live=5 label=5 agree
- g-importance-0003 stub=5 live=5 label=5 agree
- g-importance-0004 stub=5 live=5 label=5 agree
- g-importance-0005 stub=5 live=5 label=5 agree
- g-importance-0006 stub=5 live=5 label=5 agree
- g-importance-0007 stub=4 live=4 label=4 agree
- g-importance-0008 stub=4 live=4 label=4 agree
- g-importance-0009 stub=4 live=4 label=4 agree
- g-importance-0010 stub=4 live=4 label=4 agree
- g-importance-0011 stub=4 live=4 label=4 agree
- g-importance-0012 stub=4 live=5 label=4 differ
- g-importance-0013 stub=4 live=4 label=4 agree
- g-importance-0014 stub=4 live=4 label=4 agree
- g-importance-0015 stub=4 live=4 label=4 agree
- g-importance-0016 stub=4 live=4 label=4 agree
- g-importance-0017 stub=1 live=1 label=1 agree
- g-importance-0018 stub=1 live=1 label=1 agree
- g-importance-0019 stub=1 live=1 label=1 agree
- g-importance-0020 stub=1 live=1 label=1 agree
- g-importance-0021 stub=2 live=5 label=2 differ
- g-importance-0022 stub=2 live=5 label=2 differ
- g-importance-0023 stub=2 live=3 label=2 differ
- g-importance-0024 stub=2 live=2 label=2 agree
