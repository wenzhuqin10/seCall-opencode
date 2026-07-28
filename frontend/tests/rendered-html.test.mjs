import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

async function render() {
  const workerUrl = new URL("../dist/server/index.js", import.meta.url);
  workerUrl.searchParams.set("test", `${process.pid}-${Date.now()}`);
  const { default: worker } = await import(workerUrl.href);

  return worker.fetch(
    new Request("http://localhost/", {
      headers: { accept: "text/html" },
    }),
    {
      ASSETS: {
        fetch: async () => new Response("Not found", { status: 404 }),
      },
    },
    {
      waitUntil() {},
      passThroughOnException() {},
    },
  );
}

test("server-renders the seCall OpenCode Studio", async () => {
  const response = await render();
  assert.equal(response.status, 200);
  assert.match(response.headers.get("content-type") ?? "", /^text\/html\b/i);

  const html = await response.text();
  assert.match(html, /<title>seCall OpenCode Studio<\/title>/i);
  assert.match(html, /KNOWLEDGE OPERATIONS/);
  assert.match(html, /搜索会话、知识或错误信息/);
  assert.match(html, /知识库/);
  assert.doesNotMatch(html, /codex-preview/);
  assert.doesNotMatch(html, /Your site is taking shape/);
});

test("contains search and knowledge management contracts", async () => {
  const [page, layout, css] = await Promise.all([
    readFile(new URL("../app/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/layout.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/globals.css", import.meta.url), "utf8"),
  ]);

  assert.match(page, /\/api\/search\?/);
  assert.match(page, /\/api\/knowledge\/trash/);
  assert.match(page, /method:\s*"PUT"/);
  assert.match(page, /method:\s*"DELETE"/);
  assert.match(page, /Ctrl K/);
  assert.match(layout, /title:\s*"seCall OpenCode Studio"/);
  assert.match(css, /\.search-popover/);
  assert.match(css, /\.knowledge-drawer/);
});
