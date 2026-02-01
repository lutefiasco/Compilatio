# Planning Considerations

Ongoing design and implementation considerations for Compilatio.

## Rotating Featured Manuscript

The landing page displays a featured manuscript, currently selected randomly via `/api/featured`. Considerations for improving this:

### Current Implementation
- Random selection from all manuscripts in database
- No weighting or curation
- Same manuscript may appear repeatedly for a user

### Potential Enhancements

**Curated Selection**
- Maintain a `featured` table with hand-picked manuscripts and optional display dates
- Allow scheduling specific manuscripts for specific dates (e.g., feast days, anniversaries)
- Fallback to random selection when no scheduled manuscript

**Visual Quality Filtering**
- Only feature manuscripts with high-quality thumbnails
- Exclude manuscripts with missing or broken images
- Prefer manuscripts with rich illumination or distinctive features

**Repository Balance**
- Rotate between repositories to ensure visibility for all sources
- Weight selection by repository size or significance

**User Experience**
- Session-based persistence (same featured manuscript during a visit)
- "Show me another" button to manually rotate
- History tracking to avoid repeating recently shown manuscripts

**Time-Based Themes**
- Liturgical calendar integration (show relevant manuscripts on feast days)
- Seasonal themes (bestiaries in spring, apocalypses in Advent)

### Implementation Notes

Current random selection is simple but effective for MVP. Curated selection would require:
- New `featured_manuscripts` table with `manuscript_id`, `display_date`, `priority`
- Admin interface or simple JSON file for managing featured list
- Modified `/api/featured` endpoint logic
