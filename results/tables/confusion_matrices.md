# Confusion matrices (test split, row = truth, column = prediction)

Categories: Normal, Infrastructure, Quality, Combined

## scenarios / F-A

| truth \ pred | Normal | Infrastructure | Quality | Combined |
|---|---|---|---|---|
| Normal | 49000 | 22947 | 4637 | 208 |
| Infrastructure | 2287 | 18667 | 396 | 695 |
| Quality | 1838 | 1439 | 2838 | 371 |
| Combined | 57 | 744 | 514 | 1782 |

## scenarios / F-B

| truth \ pred | Normal | Infrastructure | Quality | Combined |
|---|---|---|---|---|
| Normal | 61345 | 13778 | 1408 | 261 |
| Infrastructure | 5151 | 16379 | 104 | 411 |
| Quality | 3639 | 932 | 1540 | 375 |
| Combined | 324 | 911 | 359 | 1503 |

## scenarios / F-A (no temporal)

| truth \ pred | Normal | Infrastructure | Quality | Combined |
|---|---|---|---|---|
| Normal | 46053 | 24988 | 4456 | 1295 |
| Infrastructure | 2610 | 17656 | 327 | 1452 |
| Quality | 1861 | 1249 | 2324 | 1052 |
| Combined | 93 | 673 | 351 | 1980 |

## scenarios / F-B (no temporal)

| truth \ pred | Normal | Infrastructure | Quality | Combined |
|---|---|---|---|---|
| Normal | 61448 | 13747 | 1346 | 251 |
| Infrastructure | 5174 | 16394 | 89 | 388 |
| Quality | 3700 | 949 | 1482 | 355 |
| Combined | 346 | 970 | 338 | 1443 |

## scenarios / threshold voting (no fusion)

| truth \ pred | Normal | Infrastructure | Quality | Combined |
|---|---|---|---|---|
| Normal | 76046 | 110 | 636 | 0 |
| Infrastructure | 17178 | 4796 | 21 | 50 |
| Quality | 5651 | 14 | 821 | 0 |
| Combined | 1225 | 642 | 600 | 630 |

## scenarios / single joint model (no separated evidence)

| truth \ pred | Normal | Infrastructure | Quality | Combined |
|---|---|---|---|---|
| Normal | 35228 | 41221 | 282 | 61 |
| Infrastructure | 4261 | 17747 | 20 | 17 |
| Quality | 3480 | 2614 | 392 | 0 |
| Combined | 67 | 2727 | 0 | 303 |

## scenarios / baseline: fixed_threshold

| truth \ pred | Normal | Infrastructure | Quality | Combined |
|---|---|---|---|---|
| Normal | 74168 | 2369 | 252 | 3 |
| Infrastructure | 11434 | 10551 | 17 | 43 |
| Quality | 6165 | 276 | 32 | 13 |
| Combined | 1720 | 1377 | 0 | 0 |

## scenarios / baseline: isolation_forest

| truth \ pred | Normal | Infrastructure | Quality | Combined |
|---|---|---|---|---|
| Normal | 73116 | 988 | 2677 | 11 |
| Infrastructure | 20535 | 592 | 884 | 34 |
| Quality | 5848 | 27 | 611 | 0 |
| Combined | 2789 | 249 | 56 | 3 |

## battledim / F-A

| truth \ pred | Normal | Infrastructure | Quality | Combined |
|---|---|---|---|---|
| Normal | 20382 | 3659 | 0 | 0 |
| Infrastructure | 14117 | 1586 | 0 | 0 |
| Quality | 0 | 0 | 0 | 0 |
| Combined | 0 | 0 | 0 | 0 |

## battledim / F-B

| truth \ pred | Normal | Infrastructure | Quality | Combined |
|---|---|---|---|---|
| Normal | 2150 | 21891 | 0 | 0 |
| Infrastructure | 698 | 15005 | 0 | 0 |
| Quality | 0 | 0 | 0 | 0 |
| Combined | 0 | 0 | 0 | 0 |

## battledim / F-A (no temporal)

| truth \ pred | Normal | Infrastructure | Quality | Combined |
|---|---|---|---|---|
| Normal | 24041 | 0 | 0 | 0 |
| Infrastructure | 15703 | 0 | 0 | 0 |
| Quality | 0 | 0 | 0 | 0 |
| Combined | 0 | 0 | 0 | 0 |

## battledim / F-B (no temporal)

| truth \ pred | Normal | Infrastructure | Quality | Combined |
|---|---|---|---|---|
| Normal | 13310 | 10731 | 0 | 0 |
| Infrastructure | 5561 | 10142 | 0 | 0 |
| Quality | 0 | 0 | 0 | 0 |
| Combined | 0 | 0 | 0 | 0 |

## battledim / threshold voting (no fusion)

| truth \ pred | Normal | Infrastructure | Quality | Combined |
|---|---|---|---|---|
| Normal | 0 | 24041 | 0 | 0 |
| Infrastructure | 0 | 15703 | 0 | 0 |
| Quality | 0 | 0 | 0 | 0 |
| Combined | 0 | 0 | 0 | 0 |

## battledim / single joint model (no separated evidence)

| truth \ pred | Normal | Infrastructure | Quality | Combined |
|---|---|---|---|---|
| Normal | 1300 | 22741 | 0 | 0 |
| Infrastructure | 1364 | 14339 | 0 | 0 |
| Quality | 0 | 0 | 0 | 0 |
| Combined | 0 | 0 | 0 | 0 |

## battledim / baseline: fixed_threshold

| truth \ pred | Normal | Infrastructure | Quality | Combined |
|---|---|---|---|---|
| Normal | 23995 | 46 | 0 | 0 |
| Infrastructure | 15611 | 92 | 0 | 0 |
| Quality | 0 | 0 | 0 | 0 |
| Combined | 0 | 0 | 0 | 0 |

## battledim / baseline: isolation_forest

| truth \ pred | Normal | Infrastructure | Quality | Combined |
|---|---|---|---|---|
| Normal | 23662 | 379 | 0 | 0 |
| Infrastructure | 15441 | 262 | 0 | 0 |
| Quality | 0 | 0 | 0 | 0 |
| Combined | 0 | 0 | 0 | 0 |

