# Compilatio

A quick-and-dirty site that assembles completely digitized medieval manuscripts (mostly from UK repositories) in one location. It's not at all groundbreaking, but it is a bit of a convenience in making visible what's available.

**Live site:** https://oldbooks.humspace.ucla.edu/

## Repositories

| Repository | Manuscripts |
|------------|-------------|
| Bodleian Library | 1,713 |
| Cambridge University Library | 304 |
| Durham University Library | 287 |
| National Library of Wales | 249 |
| Huntington Library | 190 |
| British Library | 178 |
| UCLA Library | 115 |
| National Library of Scotland | 104 |
| Lambeth Palace Library | 2 |
| **Total** | **3,119** |

## Features

- Browse by repository, collection, and manuscript
- OpenSeadragon IIIF viewer with metadata sidebar
- Visual attribution to source institutions
- Dark theme, manuscript-forward design

## Tech Stack

- **Production:** PHP 8 / MySQL (hosted on UCLA Humspace)
- **Development:** Python / Starlette / SQLite
- **Frontend:** Vanilla HTML/CSS/JavaScript
- **Viewer:** OpenSeadragon 4.1.1

## Local Development

```bash
# Clone and set up
git clone https://github.com/lutefiasco/Compilatio.git
cd Compilatio

# Run the development server
python server.py
```

Visit http://localhost:8000

## Project Status

See [Compilatio_Project_Status.md](Compilatio_Project_Status.md) for detailed implementation status.
