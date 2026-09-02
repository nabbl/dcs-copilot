# MARA early-access website

The public MARA landing page, roadmap, and Markdown-driven flight manual.

## Local development

```bash
npm ci
npm run dev
```

## Builds

- `npm run build` validates the Cloudflare-compatible preview build.
- `npm run build:pages` creates the static GitHub Pages site in `out/`.
- `npm run test:pages` verifies the exported routes, assets, metadata, and project-relative navigation.

The documentation source lives in `content/manual.md`. Pushes that change
`website/` automatically publish through `.github/workflows/pages.yml`.
