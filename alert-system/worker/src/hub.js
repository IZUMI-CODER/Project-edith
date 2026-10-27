// A single Durable Object holding every phone's direct WebSocket, tagged by its topic.
// It pings all phones every 30 s so Wi-Fi extenders and NATs that cut "idle"
// connections never see this one as idle. Uses the hibernation API, so it costs
// nothing between pings. Nothing is stored except the next ping time.

const PING_MS = 30_000;
const TOPIC_RE = /^edith-[0-9a-f]{64}$/;

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
    if (sockets.length) await this.ctx.storage.setAlarm(Date.now() + PING_MS);
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
