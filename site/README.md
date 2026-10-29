# wanna.sh website

The public product page and documentation, built with [Astro](https://astro.build) and
[Starlight](https://starlight.astro.build), and published to GitHub Pages by `.github/workflows/site.yml`.

```bash
cd site
npm ci
npm run dev       # http://localhost:4321/wanna/
npm run build     # static site in dist/
```

- `src/pages/index.astro`: the landing page.
- `src/content/docs/docs/`: the docs, one Markdown file per page. Add new pages to the sidebar in `astro.config.mjs`.
- `src/assets/screens/`: app screenshots used in the docs. `public/art/`: the paintings (shared with the app).

Write links from the site root, like `[Install](/docs/start/install/)`; `src/plugins/base-links.mjs` adds the base path.

## Where it's published

By default the site is built for `https://wanna-sh.github.io/wanna/`. To use a custom domain, set the repository
variable `SITE_DOMAIN` (for example `wanna.sh`); the build then uses `/` as its base and writes the `CNAME` file. Locally:
`SITE_DOMAIN=wanna.sh npm run build`.
