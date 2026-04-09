# The Street Cleaning Game

A single-page web app for managing alternate side parking in Fort Greene, Brooklyn.

## Architecture

- **Single `index.html`** — vanilla HTML/CSS/JS, no dependencies, no build step
- **Data**: Hardcoded 2026 NYC ASP suspension calendar from NYC DOT
- **Storage**: `localStorage` for user preferences
- **Hosting**: GitHub Pages

## ASP Calendar

The 2026 suspension dates are hardcoded in `index.html`. Source: [NYC DOT ASP Calendar](https://www.nyc.gov/html/dot/downloads/pdf/asp-calendar-2026.pdf). Update annually.

## User Context

- Fort Greene, Brooklyn
- Available spot types: Monday, Tuesday, Thursday, Friday
- Works M-F, leaves 8:30am, returns 5:15pm
- Cannot move car during cleaning hours (always during work hours)
