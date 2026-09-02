import assert from "node:assert/strict";
import { access, readFile } from "node:fs/promises";
import test from "node:test";

const output = new URL("../out/", import.meta.url);

test("exports every public route", async () => {
  await Promise.all([
    access(new URL("index.html", output)),
    access(new URL("docs/index.html", output)),
    access(new URL("roadmap/index.html", output)),
    access(new URL("mara-portrait.jpg", output)),
    access(new URL("og.png", output)),
  ]);
});

test("uses the GitHub Pages base path for generated assets", async () => {
  const html = await readFile(new URL("index.html", output), "utf8");
  assert.match(html, /\/mara-site\/_next\/static\//);
  assert.match(html, /href="\.\/docs\/"/);
  assert.match(html, /href="\.\/roadmap\/"/);
  assert.match(html, /https:\/\/nabbl\.github\.io\/mara-site\/og\.png/);
  assert.doesNotMatch(html, /href="\/(?:docs|roadmap)"/);
});

test("keeps nested-page navigation inside the project site", async () => {
  const docs = await readFile(new URL("docs/index.html", output), "utf8");
  const roadmap = await readFile(new URL("roadmap/index.html", output), "utf8");
  assert.match(docs, /href="\.\.\/roadmap\/"/);
  assert.match(roadmap, /href="\.\.\/docs\/"/);
});
