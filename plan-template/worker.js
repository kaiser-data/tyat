// private page: ?k=<PLAN_KEY> once sets a cookie; everything else gets 401
async function guard(request, env, next) {
  const url = new URL(request.url), key = env.PLAN_KEY;
  if (!key) return new Response("not configured", { status: 503 });
  const cookie = request.headers.get("cookie") || "";
  if (url.searchParams.get("k") === key) {
    const res = await next();
    const out = new Response(res.body, res);
    out.headers.append("set-cookie", `pk=${key}; Path=/; Max-Age=31536000; Secure; HttpOnly; SameSite=Lax`);
    out.headers.set("cache-control", "no-store");
    return out;
  }
  if (cookie.split(/;\s*/).includes(`pk=${key}`)) return next();
  return new Response("🔒", { status: 401, headers: { "content-type": "text/plain; charset=utf-8" } });
}

// feedback inbox: the page POSTs voice memos or notes, `t inbox` on the Mac lists, fetches and deletes them
const MAX = 20 * 1024 * 1024;
async function inbox(request, env, path) {
  const json = (x, status = 200) => new Response(JSON.stringify(x), { status, headers: { "content-type": "application/json" } });
  if (path === "/api/inbox" && request.method === "POST") {
    const type = (request.headers.get("content-type") || "application/octet-stream").split(";")[0];
    if (!/^(audio\/|text\/plain)/.test(type)) return json({ error: "audio or text only" }, 415);
    const body = await request.arrayBuffer();
    if (!body.byteLength || body.byteLength > MAX) return json({ error: "empty or too big" }, 413);
    const id = `${Date.now()}-${crypto.randomUUID().slice(0, 8)}`;
    await env.INBOX.put(id, body, { metadata: { type, size: body.byteLength } });
    return json({ id }, 201);
  }
  if (path === "/api/inbox" && request.method === "GET") {
    const { keys } = await env.INBOX.list();
    return json(keys.map(k => ({ id: k.name, ...k.metadata })));
  }
  const m = path.match(/^\/api\/inbox\/([\w-]+)$/);
  if (m && request.method === "GET") {
    const { value, metadata } = await env.INBOX.getWithMetadata(m[1], { type: "arrayBuffer" });
    return value ? new Response(value, { headers: { "content-type": metadata?.type || "application/octet-stream" } }) : json({ error: "gone" }, 404);
  }
  if (m && request.method === "DELETE") { await env.INBOX.delete(m[1]); return json({ ok: true }); }
  return json({ error: "no such route" }, 404);
}

export default {
  fetch(request, env) {
    const path = new URL(request.url).pathname;
    return guard(request, env, () => path.startsWith("/api/") ? inbox(request, env, path) : env.ASSETS.fetch(request));
  },
};
