# Compilatio — Active Planning

Forward-looking work items for the Compilatio IIIF manuscript aggregator. Newest at top.
For current production state (deployment, data summary, importer scripts, known issues)
see `Feb04_2026_Status.md` at the repo root.

Last updated: 2026-06-27.

---

## Open items

### 1. BL Charters & Rolls (Cotton / Harley) — pending ingest  *(added 2026-06-27)*

The "MSS on Rails" projects now hold the BL charter/roll records natively: **Harley
77 charters + 12 rolls**, **Cotton 45 rolls** (+ 209 charters). After the 2026-06-27
`catalogue_url` correction (Scriptorium `tools/fix_charter_roll_catalogue_urls.py`),
each row carries the searcharchives catalogue URL and, where one exists, a BL
`digitised_url`. **We want these materials in Compilatio** so the charters/rolls gain
IIIF viewers and the cross-project IIIF dot — today they have neither.

**Caveat — only a subset is IIIF-ingestable now.** The Harley rolls carry real IIIF
manifests (`iiif.bl.uk` / `bl.digirati.io`); but most charter and Cotton-roll links are
the legacy `FullDisplay.aspx` / `access.bl.uk` viewers marked "digital images currently
unavailable" (no IIIF manifest). Ingest the manifest-bearing subset first; revisit the
rest as the BL digitises them. Candidate manifests are discoverable from the on-Rails
DBs' `digitised_url` (filter to `iiif.bl.uk` / `digirati`) or by querying the BL IIIF
endpoint by `bl_record_id`. Folds into the existing **British Library** repository
(178 MSS today), not a new source.

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

- **2026-06-27** — Doc created. Inaugural item: ingest the Cotton/Harley BL charters &
  rolls (now carrying IIIF/digitised manifests after the Scriptorium catalogue_url fix)
  into Compilatio's BL coverage, manifest-bearing subset first. (Moved here from a note
  briefly placed in the gitignored `Feb04_2026_Status.md`.)
