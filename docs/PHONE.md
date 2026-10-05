# Using it on your phone

The page is an installable web app (manifest + service worker): open it in the phone browser,
then "Add to Home Screen". Swipe left/right or tap the hint text to move through the ladder.

## Three ways to reach it from a phone

1. **Same Wi-Fi, quickest.** `uvicorn server:app --host 0.0.0.0 --port 8000`, then open
   `http://<laptop-ip>:8000`. Plain HTTP is not a "secure context", so the live camera preview is
   blocked, but the **Upload** button opens the phone's native camera and works fine.
2. **HTTPS tunnel (live camera works).** `cloudflared tunnel --url http://localhost:8000`
   (or `ngrok http 8000`) prints an https URL. Open that on the phone.
3. **Deploy it** (Render, Fly.io, Railway, a VPS): run `uvicorn server:app --host 0.0.0.0 --port $PORT`
   behind their HTTPS.

## Protect your API credit
Anyone with the URL can make the server call the paid API. Whenever it is reachable from the internet
(options 2 and 3) set an access code; the page asks for it once and remembers it:

    ACCESS_CODE=pick-something-long ANTHROPIC_API_KEY=sk-ant-... uvicorn server:app --port 8000

Also set a monthly spend limit in the Anthropic console. Never commit the key.
