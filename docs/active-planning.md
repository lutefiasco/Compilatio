# Compilatio — Active Planning

Forward-looking work items for the Compilatio IIIF manuscript aggregator. Newest at top.
For current production state (deployment, data summary, importer scripts, known issues)
see `Feb04_2026_Status.md` at the repo root.

Last updated: 2026-08-06.

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

### Audit the design and CSS choices  *(opened 2026-08-06)*

The accessibility work has repeatedly turned up CSS that outlived the markup it was written
for, and the pattern is consistent enough now to be worth a deliberate pass rather than
another incidental discovery.

**What prompted it.** Building the viewer's narrow-width layout (step 4a, `0c7396d`)
surfaced that `css/styles.css:1078–1260` carries a complete responsive viewer — slide-in
drawer at ≤1024px, bottom sheet with a drag handle at ≤768px, `.sidebar-toggle-mobile`,
`.sidebar-overlay`. It targets `.viewer-layout` / `.manuscript-sidebar`, markup that exists
only in `src/archive/` (`viewer_uv_original.html` and the `Viewer_Test*` prototypes). The
live `src/viewer.html` uses different class names, links **no stylesheet at all**, and had
zero media queries. So the site appeared to have mobile support it did not have, and the
appearance was persuasive enough to shape a design discussion before being checked. Two
sibling instances are already on record: the dead root `styles.css`, and
`Scriptorium/static/css/compilatio.css` (removed in `d6a2f2a`).

**What the pass should cover.**

- **Dead rules.** Which selectors in `css/styles.css` match nothing on any live page?
  Machine-checkable: render all four pages, collect matched selectors, diff against the
  parsed stylesheet. Distinguish genuinely dead from JS-applied state classes
  (`.hidden`, `.active`, `.dragging`, `.open`) that are real but not present at rest.
- **`src/viewer.html`'s self-contained CSS.** ~500 lines inline in `<head>`, sharing class
  names and colour values with `styles.css` but no cascade. Decide deliberately whether
  that isolation is the design (it did keep the viewer immune to sitewide regressions) or
  an accident to be reconciled. It is why the viewer inherited neither the responsive work
  nor, until step 1, the contrast tokens.
- **Token discipline.** Contrast tokens landed in `9013152`, but literal hex values are
  still scattered through both stylesheets — `#1a1a1a`, `#232323`, `#2a2a2a`, `#141414`,
  `#1e1e1e` as backgrounds; `#333`, `#444`, `#555` as borders. The tokens fixed the failing
  values without retiring the mechanism that produced them.
- **Breakpoints.** Three in `styles.css` (1024 / 768 / 480), one in `viewer.html` (640),
  chosen independently. Are they a system, and do the two files agree about what "narrow"
  means?
- **`src/archive/`.** Seven superseded viewer prototypes. Keep as provenance, or retire?
  If they stay, the CSS serving only them should say so in a comment — that is exactly the
  signal that was missing.

Not urgent, and not a rewrite: the output is an inventory and a set of decisions, not a
restyling. See the parallel item in
[`Scriptorium/docs/active-planning.md`](../../Scriptorium/docs/active-planning.md) — the
shared `base.css` / `components.css` still carry the failing contrast tokens for the other
seven apps, and the same dead-CSS question applies there.

### Remaining accessibility work (steps 4b–6)

Not yet done, none blocked: skip links (2.4.1), SPA focus management on browse (4.1.3 /
2.4.3), `prefers-reduced-motion`, and `lang` on Latin / Middle English / Anglo-Norman parts
(3.1.2 — needs per-field language data, deliberately deferred rather than overlooked).
Step 4a (viewer reflow) is committed but **not deployed**; the About changelog entry for it
is deliberately unwritten pending that call.

See **Pointers** below and `Feb04_2026_Status.md` for the near-term TODO and
repository-expansion candidates.

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

- **2026-08-06** — Added the design/CSS audit item and the steps 4b–6 accessibility
  summary. Prompted by step 4a (`0c7396d`), which found `styles.css`'s responsive viewer
  serving only archived Universal Viewer markup while the live viewer had no breakpoints
  at all. A parallel CSS re-audit item was filed in Scriptorium's planning doc.
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
