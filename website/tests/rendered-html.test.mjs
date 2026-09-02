import assert from "node:assert/strict";
import test from "node:test";

async function render(pathname = "/") {
  const workerUrl = new URL("../dist/server/index.js", import.meta.url);
  workerUrl.searchParams.set("test", `${process.pid}-${Date.now()}-${pathname}`);
  const { default: worker } = await import(workerUrl.href);

  return worker.fetch(
    new Request(`http://localhost${pathname}`, { headers: { accept: "text/html" } }),
    { ASSETS: { fetch: async () => new Response("Not found", { status: 404 }) } },
    { waitUntil() {}, passThroughOnException() {} },
  );
}

test("server-renders the MARA landing page", async () => {
  const response = await render("/");
  assert.equal(response.status, 200);
  const html = await response.text();
  assert.match(html, /<title>MARA — Your second seat in DCS<\/title>/i);
  assert.match(html, /Your second seat/);
  assert.match(html, /Read the flight manual/);
  assert.match(html, /mara-portrait\.jpg/);
  assert.doesNotMatch(html, /codex-preview|SkeletonPreview|react-loading-skeleton/i);
});

test("server-renders Markdown documentation", async () => {
  const response = await render("/docs");
  assert.equal(response.status, 200);
  const html = await response.text();
  assert.match(html, /Flight manual/);
  assert.match(html, /id="choose-your-setup"/);
  assert.match(html, /All-in-one install/);
  assert.match(html, /Split install/);
  assert.match(html, /Local mode requires your own OpenAI API key/);
  assert.match(html, /Windows Credential Manager/);
  assert.match(html, /configure the OpenAI API key on the <strong>backend machine<\/strong>/);
  assert.match(html, /id="start-here"/);
  assert.match(html, /id="privacy-boundary"/);
  assert.match(html, /MARA cannot see DCS/);
});

test("server-renders the roadmap and current scope", async () => {
  const response = await render("/roadmap");
  assert.equal(response.status, 200);
  const html = await response.text();
  assert.match(html, /MARA Roadmap/);
  assert.match(html, /Combat awareness/);
  assert.match(html, /Helicopter support/);
  assert.match(html, /The code will be public/i);
  assert.match(html, /ko-fi\.com\/nabblsawesome/);
});
