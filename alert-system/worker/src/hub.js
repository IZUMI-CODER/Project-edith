// A single Durable Object holding every phone's direct WebSocket, tagged by its topic.
// It pings all phones every 30 s so Wi-Fi extenders and NATs that cut "idle"
// connections never see this one as idle. Uses the hibernation API, so it costs
// nothing between pings. The only things stored are the next ping time and voice
// messages, which are deleted 15 minutes after they're sent.

const PING_MS = 30_000;
const VOICE_TTL_MS = 15 * 60_000;
const TOPIC_RE = /^edith-[0-9a-f]{64}$/;
const ID_RE = /^[0-9a-f-]{36}$/;

export class AlertHub {
  constructor(ctx) {
    this.ctx = ctx;
  }

  async fetch(request) {
    const url = new URL(request.url);

    if (url.pathname === "/listen") {
      const topic = url.searchParams.get("topic") || "";
      if (!TOPIC_RE.test(topic)) return new Response("bad topic", { status: 400 });
      const { 0: client, 1: server } = new WebSocketPair();
      this.ctx.acceptWebSocket(server, [topic]);
      server.send("ping");
      await this.scheduleAlarm();
      return new Response(null, { status: 101, webSocket: client });
    }

    if (url.pathname === "/broadcast" && request.method === "POST") {
      const { topics, data } = await request.json();
      const payload = JSON.stringify(data);
      const connected = {};
      for (const topic of topics) {
        let n = 0;
        for (const ws of this.ctx.getWebSockets(topic)) {
          try {
            ws.send(payload);
            n++;
          } catch {
            // socket already gone; the runtime cleans it up
          }
        }
        connected[topic] = n;
      }
      return Response.json(connected);
    }

    if (url.pathname === "/voice/put" && request.method === "POST") {
      const { id, topics, mime, b64 } = await request.json();
      const data = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
      await this.ctx.storage.put(`voice:${id}`, { mime, topics, at: Date.now(), data });
      await this.scheduleAlarm();
      return new Response("ok");
    }

    if (url.pathname === "/voice/get") {
      const id = url.searchParams.get("id") || "";
      const topic = url.searchParams.get("topic") || "";
      if (!ID_RE.test(id) || !TOPIC_RE.test(topic)) return new Response("bad request", { status: 400 });
      const voice = await this.ctx.storage.get(`voice:${id}`);
      // Only phones the message was sent to can fetch it.
      if (!voice || !voice.topics.includes(topic) || Date.now() - voice.at > VOICE_TTL_MS) {
        return new Response("not found", { status: 404 });
      }
      return new Response(voice.data, { headers: { "content-type": voice.mime, "cache-control": "no-store" } });
    }

    return new Response("not found", { status: 404 });
  }

  async scheduleAlarm() {
    if ((await this.ctx.storage.getAlarm()) === null) {
      await this.ctx.storage.setAlarm(Date.now() + PING_MS);
    }
  }

  async alarm() {
    const sockets = this.ctx.getWebSockets();
    for (const ws of sockets) {
      try {
        ws.send("ping");
      } catch {
        // ignore; closed sockets drop out of getWebSockets()
      }
    }
    const voices = await this.ctx.storage.list({ prefix: "voice:" });
    let kept = 0;
    for (const [key, voice] of voices) {
      if (Date.now() - voice.at > VOICE_TTL_MS) await this.ctx.storage.delete(key);
      else kept++;
    }
    if (sockets.length || kept) await this.ctx.storage.setAlarm(Date.now() + PING_MS);
  }

  async webSocketMessage() {
    // Phones only listen; anything they send is ignored.
  }

  async webSocketClose(ws, code) {
    try {
      ws.close(code === 1005 ? 1000 : code, "bye");
    } catch {
      // already closed
    }
  }

  async webSocketError() {}
}

export function isTopic(s) {
  return TOPIC_RE.test(s);
}

export function isAlertId(s) {
  return ID_RE.test(s);
}
