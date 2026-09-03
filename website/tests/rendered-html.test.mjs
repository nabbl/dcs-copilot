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
  assert.match(html, /<title>MARA — Your copilot for DCS<\/title>/i);
  assert.match(html, /Your copilot[\s\S]*for DCS/);
  assert.match(html, /Get started/);
  assert.match(html, /Hands on the HOTAS/);
  assert.match(html, /MARA itself is free/);
  assert.match(html, /any model usage is billed directly to your OpenAI account/);
  assert.match(html, /How MARA[\s\S]*works/);
  assert.match(html, /No MARA account is required/);
  assert.match(html, /respects the export and telemetry restrictions/);
  assert.match(html, /id="roadmap"/);
  assert.match(html, /Radar assistance/);
  assert.match(html, /using only information already available in your cockpit/);
  assert.match(html, /Helicopter support/);
  assert.match(html, /important local warnings working even if the AI service/);
  assert.match(html, /working roadmap, not a release schedule/);
  assert.match(html, /Why I built this/);
  assert.match(html, /Community project/);
  assert.match(html, /Support on Ko-fi/);
  assert.match(html, /mara-portrait\.jpg/);
  assert.doesNotMatch(html, /codex-preview|SkeletonPreview|react-loading-skeleton/i);
});

test("server-renders Markdown documentation", async () => {
  const response = await render("/docs");
  assert.equal(response.status, 200);
  const html = await response.text();
  assert.match(html, /Flight manual/);
  assert.match(html, /MARA is free\. OpenAI usage is not/);
  assert.match(html, /There is no MARA purchase price or subscription/);
  assert.match(html, /real-time voice pipeline/);
  assert.match(html, /only paid external service required/);
  assert.match(html, /id="before-you-install"/);
  assert.match(html, /64-bit Windows PC/);
  assert.match(html, /Windows defaults or separate microphone/);
  assert.match(html, /Ctrl, Alt, Shift, and Win modifiers/);
  assert.match(html, /Configure your flight audio in MARA/);
  assert.match(html, /roughly 340 MB of Kokoro voice files/);
  assert.match(html, /currently unsigned/);
  assert.match(html, /id="choose-your-setup"/);
  assert.match(html, /All-in-one install/);
  assert.match(html, /Split install/);
  assert.match(html, /Local mode requires your own OpenAI API key/);
  assert.match(html, /Windows Credential Manager/);
  assert.match(html, /Configure your OpenAI API key on the <strong>backend machine<\/strong>/);
  assert.match(html, /id="what-the-dcs-setup-changes"/);
  assert.match(html, /Scripts\\Export\.lua/);
  assert.match(html, /id="start-here"/);
  assert.match(html, /id="privacy-boundary"/);
  assert.match(html, /MARA cannot see DCS/);
});

test("server-renders the roadmap and current scope", async () => {
  const response = await render("/roadmap");
  assert.equal(response.status, 200);
  const html = await response.text();
  assert.match(html, /MARA Roadmap/);
  assert.match(html, /Radar assistance/);
  assert.match(html, /Helicopter support/);
  assert.match(html, /The code is public/i);
  assert.match(html, /github\.com\/nabbl\/dcs-copilot/);
});
