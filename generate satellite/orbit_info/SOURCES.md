# Verified official orbital parameters

Verified on 2026-10-05. Original PDFs are stored in `official_documents/`; URLs, dates, and SHA256 hashes are in `sources.json`. These tables provide research inputs from the specified approval versions. Application acceptance, operator plans, and third-party interference models are not treated as approvals.

## Amazon Kuiper / Amazon Leo Gen1

[FCC DA 24-224, 2024-03-08](https://docs.fcc.gov/public/attachments/DA-24-224A1.pdf), paragraphs 1 and 4 and footnote 11, approves the modified constellation parameters:

| Altitude km | Inclination ° | Orbital planes | Satellites per plane | Total |
|---:|---:|---:|---:|---:|
| 590 | 33 | 782 | 1 | 782 |
| 590 | 30 | 1 | 2 | 2 |
| 610 | 42 | 1292 | 1 | 1292 |
| 630 | 51.9 | 289 | 4 | 1156 |

Total: 3,232. This table uses the modified approved plane counts instead of the older 98-plane, 3,236-satellite configuration. Plane counts are authorization parameters and do not establish that actual satellites have uniformly spaced RAANs.

[FCC DA 26-553, 2026-06-05](https://docs.fcc.gov/public/attachments/DA-26-553A1.pdf), paragraph 3 and footnote 8, still cites 3,232 Gen1 satellites and mentions Gen2 (3,212) and Polar (1,292), approved on 2026-02-10. Paragraphs 12–13 grant a limited waiver of the Gen1 interim deployment milestone. Passing 2026-07-30 therefore does not, by itself, justify reducing the approved population to the number already launched.

**The implementation is explicitly limited to Gen1.** The verified 2026 document does not list the complete approved Gen2/Polar shells and grant-stamp conditions. Those systems are therefore excluded from the machine-readable approval table for now; this does not imply that they are unapproved. Adding them requires checking the final grants and applicable conditions for `SAT-LOA-20211104-00145` / `SAT-AMD-20250311-00068`. The current scope is sufficient to generate a separate scenario that fills estimated gaps in the approved shells using the current Kuiper catalog.

## OneWeb Phase1

[FCC DA 23-362, 2023-04-28](https://docs.fcc.gov/public/attachments/DA-23-362A1.pdf), paragraph 26, approves the US market-access configuration. Paragraphs 2 and 12 specify or retain an operating altitude of approximately 1200 km:

| Altitude km | Inclination ° | Orbital planes | Satellites per plane | Total |
|---:|---:|---:|---:|---:|
| 1200 | 87.9 | 12 | 49 | 588 |
| 1200 | 55 | 8 | 16 | 128 |

Total: 716. This is an FCC market-access approval, not a substitute for UK launch or operating licenses. Count the two inclination shells separately instead of subtracting the entire deployed polar catalog from 716. Paragraph 1 defers the remaining application to expand to 6,372 satellites; this project does not label that application population as approved.

## Parameters not supplied by the official documents

Approved altitude, inclination, plane count, and satellite count constrain the orbital templates. The cited documents do not supply future per-satellite epochs, RAAN origins, inter-plane phases, mean anomalies, deployment order, service status, or an exact list of unlaunched satellites. The code explicitly assumes a simulation epoch, circular mean orbits, zero drag, and phase distributions, recorded in `generated/.../assumptions.json` and `synthetic_mean_elements.csv`. These outputs are `approved_shell_synthetic`; they are neither real TLEs nor official position forecasts.

Searches of UK/European regulatory material surfaced third-party licensing attachments with several OneWeb interference-analysis configurations. Those attachments were not treated as evidence of OneWeb's own approved constellation. The tables here use only the downloaded and verified FCC decisions.
