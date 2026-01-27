# Decoration Plan: Border Design for Compilatio

## Source Image

**Manuscript**: Bodleian Library MS. Ashmole 764
**URL**: https://digital.bodleian.ox.ac.uk/objects/ea22834d-7e38-4af6-88c8-6f38249e3d05/
**IIIF Image**: https://iiif.bodleian.ox.ac.uk/iiif/image/ff2f33f0-1798-4aef-bf77-478ae94df74a/full/1200,/0/default.jpg

## Border Characteristics

- **Style**: Delicate pen-flourished vine scrollwork (white-vine interlace)
- **Colors**: Black ink linework on cream parchment, with small blue flower/berry accents and occasional gold touches
- **Pattern**: Flowing, curling vine tendrils that loop and spiral organically
- **Character**: Light, airy, and elegant - very different from heavy geometric borders

## Intended Use

Background decorative element for Compilatio redesign, positioned at **top and right margins**.

## Implementation Approaches

### 1. Inverted/Ghosted Version
Extract the border pattern and render it in very subtle light gray (5-10% opacity) on the #2a2a2a dark background. The vine scrollwork would create atmospheric texture without competing with manuscript thumbnails.

### 2. Corner/Edge Treatment
Use the border as an L-shaped frame element at top-right, fading out toward the center. This evokes manuscript marginalia while keeping focus on content.

### 3. Color Adaptation
Keep the vine pattern but render it in muted gold (#8b7355 or similar) at low opacity for a subtle illuminated manuscript feel that complements the dark theme.

### 4. SVG Trace
The pattern is clean enough to trace as vector art, making it:
- Scalable to any resolution
- Easy to color-match the theme
- Lightweight for page load
- Animatable if desired

## IIIF Cropping

The IIIF API allows extracting just the border regions:
- Top border: `/0,0,2764,400/1000,/0/default.jpg`
- Right border: `/2400,0,364,4144/,800/0/default.jpg`

## Implementation Status

**Complete** - Using approach #1 (Inverted/Ghosted) with color adaptation.

- [x] Extract border region from source image (IIIF crops)
- [x] Downloaded to `src/images/border-top.jpg` and `src/images/border-right.jpg`
- [x] Applied CSS filters: `invert(0.72) sepia(0.55) saturate(1) brightness(0.6)`
- [x] Opacity: 24% (top), 20% (right)
- [x] Gradient masks fade toward center
- [x] Applied to all pages via `styles.css` body::before and body::after
