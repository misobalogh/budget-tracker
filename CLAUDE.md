# Budget tracker

Osobný/rodinný rozpočet z ČSOB SK CSV exportov. Všetko beží lokálne.

## Stack
Python 3.12, pandas, PyYAML, pytest, uv. Žiadne cloudové služby.

## Pravidlá
- Bankové dáta (data/) nikdy necommitovať ani nelogovať.
- Kategorizácia je rule-based: rules.yaml (kľúčové slová/regex -> kategória), prvé zhodné pravidlo vyhráva.
- Parser izolovaný v parsers/csob.py (kódovanie, oddeľovač, formát čísel a dátumov riešiť tam), aby sa dali pridať iné banky.
- Každá nová logika má pytest test na anonymizovaných fixtures v tests/fixtures/.

## Výstup
Mesačný súhrn: príjmy, fixné, variabilné, zostatok + zoznam nekategorizovaných transakcií.
