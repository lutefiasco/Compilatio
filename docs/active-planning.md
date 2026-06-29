# Compilatio — Active Planning

Forward-looking work items for the Compilatio IIIF manuscript aggregator. Newest at top.
For current production state (deployment, data summary, importer scripts, known issues)
see `Feb04_2026_Status.md` at the repo root.

Last updated: 2026-06-29.

---

## Recently landed

### BL Charters & Rolls (Cotton / Harley) — ✅ LANDED 2026-06-29  *(opened 2026-06-27)*

**107 British Library charters & rolls are now in Compilatio**, each with a working IIIF
viewer and the cross-project IIIF dot they previously lacked. Breakdown by press / class:

| Collection | Count | Presses / classes |
|---|---|---|
| Cotton Charters | 59 | Roman-numeral charter classes IV–XXIII (heaviest VIII ×25, XII ×11) |
| Cotton Rolls | 1 | Roll XIV |
| Harley Charters | 44 | charter classes 43–112 (43 C ×8, 57 B ×6, 83 A ×3) |
| Harley Rolls | 3 | Roll Y ×2, Roll T ×1 |

These fold into the existing **British Library** repository, which rises **687 → 794 MSS**.
Compilatio's overall total is now **5,351 manuscripts across 14 repositories** (was 5,244).

Native shelfmark forms are preserved verbatim (`Cotton Charter VIII 11`, `Harley Roll Y 6`)
so they match the Scriptorium concordance, where all 107 are now linked — `compilatio_id`
backfilled, concordance Compilatio links **5,283 → 5,390**, no duplicate rows.

*Why only these 107?* Of the full Cotton/Harley charter & roll holdings, only this subset
currently carries a real `bl.digirati.io` IIIF manifest; the rest are legacy
`FullDisplay.aspx` / `access.bl.uk` viewers marked "digital images currently unavailable."
Most still-dark items are *rolls*; the charters are largely live. Revisit as the BL
digitises more.

Importer: `scripts/importers/import_bl_charters_rolls.py` (reads cotton.db + harley.db,
keeps the manifest-bearing subset, native forms, upserts by repo+shelfmark, dry-run
default; 11 unit tests on manifest-unwrap + collection classification). A latent bug in the
shared `Scriptorium/tools/build_concordance.py` `seed_compilatio` — which silently dropped
the Compilatio link whenever another project had seeded the same shelfmark first — was
fixed (TDD, 2 tests) as part of this work, so cross-project linkage is durable going
forward. DBs backed up to Offside first. **Production deploy still pending** — the new
viewers appear on oldbooks.humspace.ucla.edu only after a deploy.

---

## Open items

*None currently tracked here.* See **Pointers** below and `Feb04_2026_Status.md` for the
near-term TODO and repository-expansion candidates.

---

## Pointers (tracked elsewhere)

These live in `Feb04_2026_Status.md` — referenced here so the planning picture is in one
place:

- **Priority TODO** — current near-term work list.
- **Future Expansion Candidates** — new repositories under consideration (Walters, Morgan,
  BnF/Gallica, BSB).
- **ISOS (Irish Script on Screen)** — future TCD source.
- **Huntington HM Expansion** — 6 fully-digitised MSS kept from the 2026-02-22 discovery;
  200 Digital Scriptorium stubs discarded.

## Change record

- **2026-06-29** — Ground-truthed item 1 against the on-Rails DBs: **107** charter/roll
  records carry a real IIIF manifest (103 charters + 4 rolls), all already present in the
  Scriptorium concordance (keyed by `cotton_id`/`harley_id`, native forms) but unlinked to
  Compilatio. Corrected the caveat above — it had charters/rolls inverted. Built
  `scripts/importers/import_bl_charters_rolls.py` (reads cotton.db + harley.db, keeps the
  manifest-bearing subset, preserves native shelfmark forms, upserts by repo+shelfmark,
  dry-run default; 11 unit tests on manifest-unwrap + collection classification) →
  4 collections: Cotton Charters / Cotton Rolls / Harley Charters / Harley Rolls.
- **2026-06-27** — Doc created. Inaugural item: ingest the Cotton/Harley BL charters &
  rolls (now carrying IIIF/digitised manifests after the Scriptorium catalogue_url fix)
  into Compilatio's BL coverage, manifest-bearing subset first. (Moved here from a note
  briefly placed in the gitignored `Feb04_2026_Status.md`.)
