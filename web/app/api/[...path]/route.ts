/**
 * Same-origin gateway to FastAPI.
 *
 * A next.config rewrite bakes its destination into the image and delegates
 * proxying to Next's generic router. This route intentionally resolves
 * BACKEND_URL for every request instead, so the standalone container uses the
 * runtime service address supplied by Compose/Coolify.
 */

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const HOP_BY_HOP_HEADERS = [
  "connection",
  "keep-alive",
  "proxy-authenticate",
  "proxy-authorization",
  "te",
  "trailer",
  "transfer-encoding",
  "upgrade",
];

async function forward(request: Request): Promise<Response> {
  const incomingUrl = new URL(request.url);
  const backendUrl = (process.env.BACKEND_URL ?? "http://127.0.0.1:8000").replace(
    /\/$/,
    "",
  );
  const targetUrl = `${backendUrl}${incomingUrl.pathname}${incomingUrl.search}`;

  const requestHeaders = new Headers(request.headers);
  requestHeaders.delete("host");
  requestHeaders.delete("content-length");
  for (const header of HOP_BY_HOP_HEADERS) requestHeaders.delete(header);

  try {
    const upstream = await fetch(targetUrl, {
      method: request.method,
      headers: requestHeaders,
      body:
        request.method === "GET" || request.method === "HEAD"
          ? undefined
          : await request.arrayBuffer(),
      cache: "no-store",
      redirect: "manual",
      signal: request.signal,
    });

    const responseHeaders = new Headers(upstream.headers);
    for (const header of HOP_BY_HOP_HEADERS) responseHeaders.delete(header);

    return new Response(upstream.body, {
      status: upstream.status,
      statusText: upstream.statusText,
      headers: responseHeaders,
    });
  } catch (error) {
    console.error("API gateway could not reach the backend", error);
    return Response.json({ detail: "API service unavailable." }, { status: 503 });
  }
}

export const GET = forward;
export const HEAD = forward;
export const POST = forward;
export const PUT = forward;
export const PATCH = forward;
export const DELETE = forward;
export const OPTIONS = forward;
