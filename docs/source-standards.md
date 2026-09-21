# What a well-behaved source looks like

Notes on practices seen in other manuscript catalogues that Compilatio should remember,
either as a bar to hold new sources to, or as things Compilatio itself does not yet do.
This is a reference, not a plan: nothing here is scheduled.

Opened 2026-09-21 after a look at manuscripta.se. Add to it as other sites turn up.

---

## manuscripta.se (looked at 2026-09-21)

The national digital catalogue of medieval and early modern manuscripts in Swedish
libraries, run from the National Library of Sweden (Kungliga biblioteket) on eXist-db.
Twelve holding institutions; the homepage counted 1,672 manuscripts, 1,584 digitised.
Newly announced in September 2026. Looked at, not scraped: the homepage, one record
(A 135, Codex Aureus), its manifest and its TEI file.

**Not currently an expansion candidate.** Its holdings are Swedish, mostly Latin, and
adding it would move Compilatio from anglophone repositories to European ones. That is a
separate decision. What follows is about the catalogue as a piece of work.

### Practices worth remembering

1. **The manifest knows where its own record is.** Each manuscript has three faces that
   cite one another: an HTML page at `/ms/<id>`, a IIIF Presentation 2 manifest at
   `/iiif/<id>/manifest.json`, and a TEI msDesc at `/ms/<id>.xml`. The manifest's
   `related` points at the page and its `seeAlso` at the TEI, with
   `format: application/tei+xml`. The manifest's `metadata` block is the msDesc in
   summary: repository, shelfmark, title, date, support, extent, language.
   *Compilatio today:* several importers scrape the catalogue record out of HTML because
   the manifest does not say where the record is. When assessing a new source, check
   `seeAlso` first; a source that fills it is cheap to import and stays importable.

2. **Dates are structured, and the display string is kept alongside.**
   `<origDate notBefore="0726" notAfter="0775">8th century, mid</origDate>`.
   *Compilatio today:* `date_start` and `date_end` exist in the schema but depend on each
   importer's parsing of prose, and are populated unevenly. This is the field most worth
   demanding of any new source, and the one most worth auditing across the existing
   fourteen.

3. **Every named thing is an authority with a URL on the same domain.** Repository,
   settlement, sponsor and bibliography item each carry a `ref` to a resolvable id
   (`/place/…`, `/org/…`, `/bibl/…`). The record also carries its identifiers in the two
   national catalogues (`idno subtype="Libris"`, `idno subtype="Regina"`).
   *Compilatio today:* no equivalent. The concordance in Scriptorium does this from the
   outside, as a side table we maintain; here it is done from the inside, in the record.
   Closer to what the chorography is reaching for than to anything in Compilatio.

4. **Two licences, stated separately and machine-readably.** Public Domain Mark on the
   images, declared in the manifest's `license`; CC BY 4.0 on the description, declared
   in the TEI `availability/licence`.
   *Compilatio today:* attribution is always shown, but no row records what the source
   permits, for images or for text. The `iiif-targets.csv` sheet has a Copyright column
   per institution; nothing per manuscript.

5. **Composite manuscripts are modelled.** Codicological units appear as nested
   `msIdentifier` blocks with their own `idno type="codicologicalUnit"`, each carrying
   its own language and extent.
   *Compilatio today:* one row per shelfmark, flattened.

6. **Canvas labels are folio references, with supplied readings marked.** The first
   canvas of A 135 is labelled `⟨f. Ir⟩`. Attribution, thumbnail and a level 1 Image API
   service are all present in the manifest.

### What it does differently, not better

- **Search-first.** The nav is Search, About, Contact. The homepage lists institutions
  with counts, but browsing is not the primary path. Compilatio chose browse-first
  deliberately, and the argument for that gets stronger, not weaker, as the count
  climbs past what a search box serves well.
- **Small, because one institution controls the whole stack.** The reason the big
  European nationals are hard is exactly the list above: IIIF everywhere, but the
  catalogue record somewhere else, in some other format, under a licence written for a
  different century. manuscripta.se is what it looks like when that is not so.

### Untested

Record enumeration (a top-level IIIF collection, sitemap, or id range) was not looked
for. Do that only if it becomes a candidate.
