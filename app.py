import os
import json
import asyncio
import secrets
import hashlib
from datetime import datetime, timedelta
from typing import Optional

from fastapi import FastAPI, Request, Response, HTTPException, Depends, Form, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
import httpx

app = FastAPI(title="CDP Browser Harness")
app.add_middleware(SessionMiddleware, secret_key=os.getenv("SESSION_SECRET", secrets.token_hex(32)))

CDP_HOST = os.getenv("CDP_HOST", "100.113.104.72")
CDP_PORT = int(os.getenv("CDP_PORT", "19222"))
CDP_URL = f"http://{CDP_HOST}:{CDP_PORT}"

UV_USERNAME = os.getenv("UV_USERNAME", "admin")
UV_PASSWORD_HASH = os.getenv("UV_PASSWORD_HASH", hashlib.sha256("changeme".encode()).hexdigest())

def verify_password(password: str) -> bool:
    return hashlib.sha256(password.encode()).hexdigest() == UV_PASSWORD_HASH

def get_current_user(request: Request):
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user

@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    user = request.session.get("user")
    if not user:
        return RedirectResponse(url="/login")
    return RedirectResponse(url="/dashboard")

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return HTMLResponse(LOGIN_HTML)

@app.post("/login")
async def login(request: Request, username: str = Form(...), password: str = Form(...)):
    if username == UV_USERNAME and verify_password(password):
        request.session["user"] = username
        return RedirectResponse(url="/dashboard", status_code=303)
    return HTMLResponse(LOGIN_HTML.replace("<!-- ERROR -->", '<p style="color:red">Invalid credentials</p>'))

@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login")

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    user = request.session.get("user")
    if not user:
        return RedirectResponse(url="/login")
    return HTMLResponse(DASHBOARD_HTML)

@app.get("/api/cdp/status")
async def cdp_status(request: Request):
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401)
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{CDP_URL}/json/version")
            return resp.json()
    except Exception as e:
        return {"error": str(e), "cdp_url": CDP_URL}

@app.get("/api/cdp/tabs")
async def cdp_tabs(request: Request):
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401)
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{CDP_URL}/json/list")
            return resp.json()
    except Exception as e:
        return {"error": str(e)}

@app.post("/api/cdp/navigate")
async def cdp_navigate(request: Request):
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401)
    body = await request.json()
    url = body.get("url", "")
    tab_id = body.get("tabId")
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            tabs = await client.get(f"{CDP_URL}/json/list")
            tabs_data = tabs.json()
            if not tabs_data:
                return {"error": "No tabs available"}
            target = tabs_data[0]
            if tab_id:
                for t in tabs_data:
                    if t["id"] == tab_id:
                        target = t
                        break
            ws_url = target.get("webSocketDebuggerUrl", "")
            if not ws_url:
                return {"error": "No WebSocket URL available"}
            import websockets
            async with websockets.connect(ws_url) as ws:
                cmd = {"id": 1, "method": "Page.navigate", "params": {"url": url}}
                await ws.send(json.dumps(cmd))
                result = await asyncio.wait_for(ws.recv(), timeout=10)
                return json.loads(result)
    except Exception as e:
        return {"error": str(e)}

@app.post("/api/cdp/screenshot")
async def cdp_screenshot(request: Request):
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401)
    body = await request.json()
    tab_id = body.get("tabId")
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            tabs = await client.get(f"{CDP_URL}/json/list")
            tabs_data = tabs.json()
            if not tabs_data:
                return {"error": "No tabs"}
            target = tabs_data[0]
            if tab_id:
                for t in tabs_data:
                    if t["id"] == tab_id:
                        target = t
                        break
            ws_url = target.get("webSocketDebuggerUrl", "")
            import websockets
            async with websockets.connect(ws_url) as ws:
                cmd = {"id": 1, "method": "Page.captureScreenshot", "params": {"format": "png"}}
                await ws.send(json.dumps(cmd))
                result = await asyncio.wait_for(ws.recv(), timeout=15)
                data = json.loads(result)
                if "result" in data and "data" in data["result"]:
                    return {"screenshot": data["result"]["data"]}
                return {"error": "No screenshot data", "raw": data}
    except Exception as e:
        return {"error": str(e)}

@app.post("/api/cdp/evaluate")
async def cdp_evaluate(request: Request):
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401)
    body = await request.json()
    expression = body.get("expression", "")
    tab_id = body.get("tabId")
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            tabs = await client.get(f"{CDP_URL}/json/list")
            tabs_data = tabs.json()
            target = tabs_data[0] if tabs_data else None
            if not target:
                return {"error": "No tabs"}
            if tab_id:
                for t in tabs_data:
                    if t["id"] == tab_id:
                        target = t
                        break
            ws_url = target.get("webSocketDebuggerUrl", "")
            import websockets
            async with websockets.connect(ws_url) as ws:
                cmd = {"id": 1, "method": "Runtime.evaluate", "params": {"expression": expression, "returnByValue": True}}
                await ws.send(json.dumps(cmd))
                result = await asyncio.wait_for(ws.recv(), timeout=10)
                return json.loads(result)
    except Exception as e:
        return {"error": str(e)}

@app.get("/api/health")
async def health():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}


LOGIN_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>CDP Harness - Login</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #0f172a; color: #e2e8f0; display: flex; align-items: center; justify-content: center; min-height: 100vh; }
        .login-card { background: #1e293b; border-radius: 12px; padding: 2rem; width: 100%; max-width: 400px; box-shadow: 0 4px 24px rgba(0,0,0,0.3); }
        h1 { text-align: center; margin-bottom: 1.5rem; color: #38bdf8; }
        .form-group { margin-bottom: 1rem; }
        label { display: block; margin-bottom: 0.5rem; font-size: 0.875rem; color: #94a3b8; }
        input { width: 100%; padding: 0.75rem; background: #0f172a; border: 1px solid #334155; border-radius: 8px; color: #e2e8f0; font-size: 1rem; }
        input:focus { outline: none; border-color: #38bdf8; }
        button { width: 100%; padding: 0.75rem; background: #38bdf8; color: #0f172a; border: none; border-radius: 8px; font-size: 1rem; font-weight: 600; cursor: pointer; margin-top: 0.5rem; }
        button:hover { background: #7dd3fc; }
        .subtitle { text-align: center; color: #64748b; margin-bottom: 1rem; font-size: 0.85rem; }
    </style>
</head>
<body>
    <div class="login-card">
        <h1>🖥️ CDP Harness</h1>
        <p class="subtitle">UV Secure Login</p>
        <!-- ERROR -->
        <form method="POST" action="/login">
            <div class="form-group">
                <label>Username</label>
                <input type="text" name="username" required autofocus>
            </div>
            <div class="form-group">
                <label>Password</label>
                <input type="password" name="password" required>
            </div>
            <button type="submit">Sign In</button>
        </form>
    </div>
</body>
</html>"""


DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>CDP Harness - Dashboard</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #0f172a; color: #e2e8f0; }
        .header { background: #1e293b; padding: 1rem 2rem; display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #334155; }
        .header h1 { color: #38bdf8; font-size: 1.25rem; }
        .header a { color: #94a3b8; text-decoration: none; }
        .container { max-width: 1200px; margin: 0 auto; padding: 2rem; }
        .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 1.5rem; margin-bottom: 1.5rem; }
        .card { background: #1e293b; border-radius: 12px; padding: 1.5rem; }
        .card h2 { color: #38bdf8; margin-bottom: 1rem; font-size: 1.1rem; }
        .status-badge { display: inline-block; padding: 0.25rem 0.75rem; border-radius: 20px; font-size: 0.8rem; font-weight: 600; }
        .status-ok { background: #065f46; color: #6ee7b7; }
        .status-err { background: #7f1d1d; color: #fca5a5; }
        pre { background: #0f172a; padding: 1rem; border-radius: 8px; overflow-x: auto; font-size: 0.8rem; max-height: 200px; overflow-y: auto; }
        .input-group { display: flex; gap: 0.5rem; margin-bottom: 1rem; }
        .input-group input { flex: 1; padding: 0.5rem; background: #0f172a; border: 1px solid #334155; border-radius: 8px; color: #e2e8f0; }
        .btn { padding: 0.5rem 1rem; background: #38bdf8; color: #0f172a; border: none; border-radius: 8px; cursor: pointer; font-weight: 600; }
        .btn:hover { background: #7dd3fc; }
        .btn-secondary { background: #475569; color: #e2e8f0; }
        .btn-secondary:hover { background: #64748b; }
        .screenshot-container { text-align: center; }
        .screenshot-container img { max-width: 100%; border-radius: 8px; border: 1px solid #334155; }
        .tabs-list { list-style: none; }
        .tabs-list li { padding: 0.5rem; border-bottom: 1px solid #334155; cursor: pointer; font-size: 0.85rem; }
        .tabs-list li:hover { background: #334155; border-radius: 4px; }
        .tabs-list .tab-url { color: #94a3b8; font-size: 0.75rem; display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        textarea { width: 100%; padding: 0.5rem; background: #0f172a; border: 1px solid #334155; border-radius: 8px; color: #e2e8f0; font-family: monospace; min-height: 80px; resize: vertical; }
        .full-width { grid-column: 1 / -1; }
    </style>
</head>
<body>
    <div class="header">
        <h1>🖥️ CDP Browser Harness</h1>
        <div>
            <span style="color:#94a3b8;margin-right:1rem;">Connected via Tailscale</span>
            <a href="/logout">Logout</a>
        </div>
    </div>
    <div class="container">
        <div class="grid">
            <div class="card">
                <h2>📡 CDP Status</h2>
                <div id="status-content">Loading...</div>
                <button class="btn btn-secondary" onclick="checkStatus()" style="margin-top:0.75rem">Refresh</button>
            </div>
            <div class="card">
                <h2>📑 Browser Tabs</h2>
                <ul class="tabs-list" id="tabs-list">Loading...</ul>
                <button class="btn btn-secondary" onclick="loadTabs()" style="margin-top:0.75rem">Refresh Tabs</button>
            </div>
            <div class="card full-width">
                <h2>🧭 Navigate</h2>
                <div class="input-group">
                    <input type="text" id="nav-url" placeholder="https://example.com" value="https://example.com">
                    <button class="btn" onclick="navigateTo()">Go</button>
                    <button class="btn btn-secondary" onclick="takeScreenshot()">📸 Screenshot</button>
                </div>
            </div>
            <div class="card">
                <h2>💻 Execute JavaScript</h2>
                <textarea id="js-code" placeholder="document.title">document.title</textarea>
                <button class="btn" onclick="evalJS()" style="margin-top:0.5rem">Execute</button>
                <pre id="eval-result" style="margin-top:0.75rem"></pre>
            </div>
            <div class="card screenshot-container">
                <h2>📸 Screenshot</h2>
                <img id="screenshot-img" src="" alt="No screenshot yet" style="display:none">
                <p id="screenshot-placeholder">Click Screenshot to capture</p>
            </div>
        </div>
    </div>
    <script>
        let selectedTabId = null;

        async function checkStatus() {
            try {
                const r = await fetch('/api/cdp/status');
                const d = await r.json();
                const el = document.getElementById('status-content');
                if (d.error) {
                    el.innerHTML = '<span class="status-badge status-err">Disconnected</span><pre>' + JSON.stringify(d, null, 2) + '</pre>';
                } else {
                    el.innerHTML = '<span class="status-badge status-ok">Connected</span><pre>' + JSON.stringify(d, null, 2) + '</pre>';
                }
            } catch (e) {
                document.getElementById('status-content').innerHTML = '<span class="status-badge status-err">Error</span><pre>' + e.message + '</pre>';
            }
        }

        async function loadTabs() {
            try {
                const r = await fetch('/api/cdp/tabs');
                const d = await r.json();
                const el = document.getElementById('tabs-list');
                if (d.error) {
                    el.innerHTML = '<li>' + d.error + '</li>';
                    return;
                }
                el.innerHTML = d.map(t => '<li onclick="selectTab(\''+t.id+'\')"><strong>' + (t.title || 'Untitled') + '</strong><span class="tab-url">' + (t.url || '') + '</span></li>').join('');
            } catch(e) {
                document.getElementById('tabs-list').innerHTML = '<li>Error: ' + e.message + '</li>';
            }
        }

        function selectTab(id) {
            selectedTabId = id;
            document.querySelectorAll('.tabs-list li').forEach(li => li.style.background = '');
            event.currentTarget.style.background = '#334155';
        }

        async function navigateTo() {
            const url = document.getElementById('nav-url').value;
            const r = await fetch('/api/cdp/navigate', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({url, tabId: selectedTabId})});
            const d = await r.json();
            if (d.error) alert('Error: ' + d.error);
            else { loadTabs(); setTimeout(takeScreenshot, 2000); }
        }

        async function takeScreenshot() {
            document.getElementById('screenshot-placeholder').textContent = 'Capturing...';
            const r = await fetch('/api/cdp/screenshot', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({tabId: selectedTabId})});
            const d = await r.json();
            if (d.screenshot) {
                const img = document.getElementById('screenshot-img');
                img.src = 'data:image/png;base64,' + d.screenshot;
                img.style.display = 'block';
                document.getElementById('screenshot-placeholder').style.display = 'none';
            } else {
                document.getElementById('screenshot-placeholder').textContent = 'Error: ' + (d.error || 'Unknown');
            }
        }

        async function evalJS() {
            const expression = document.getElementById('js-code').value;
            const r = await fetch('/api/cdp/evaluate', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({expression, tabId: selectedTabId})});
            const d = await r.json();
            document.getElementById('eval-result').textContent = JSON.stringify(d, null, 2);
        }

        checkStatus();
        loadTabs();
    </script>
</body>
</html>"""

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8080"))
    uvicorn.run(app, host="0.0.0.0", port=port)
import os
import json
import asyncio
import secrets
import hashlib
from datetime import datetime, timedelta
from typing import Optional

from fastapi import FastAPI, Request, Response, HTTPException, Depends, Form, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
import httpx

app = FastAPI(title="CDP Browser Harness")
app.add_middleware(SessionMiddleware, secret_key=os.getenv("SESSION_SECRET", secrets.token_hex(32)))

CDP_HOST = os.getenv("CDP_HOST", "100.113.104.72")
CDP_PORT = int(os.getenv("CDP_PORT", "19222"))
CDP_URL = f"http://{CDP_HOST}:{CDP_PORT}"

UV_USERNAME = os.getenv("UV_USERNAME", "admin")
UV_PASSWORD_HASH = os.getenv("UV_PASSWORD_HASH", hashlib.sha256("changeme".encode()).hexdigest())

def verify_password(password: str) -> bool:
    return hashlib.sha256(password.encode()).hexdigest() == UV_PASSWORD_HASH

def get_current_user(request: Request):
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user

@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    user = request.session.get("user")
    if not user:
        return RedirectResponse(url="/login")
    return RedirectResponse(url="/dashboard")

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return HTMLResponse(LOGIN_HTML)

@app.post("/login")
async def login(request: Request, username: str = Form(...), password: str = Form(...)):
    if username == UV_USERNAME and verify_password(password):
        request.session["user"] = username
        return RedirectResponse(url="/dashboard", status_code=303)
    return HTMLResponse(LOGIN_HTML.replace("<!-- ERROR -->", '<p style="color:red">Invalid credentials</p>'))

@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login")

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    user = request.session.get("user")
    if not user:
        return RedirectResponse(url="/login")
    return HTMLResponse(DASHBOARD_HTML)

@app.get("/api/cdp/status")
async def cdp_status(request: Request):
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401)
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{CDP_URL}/json/version")
            return resp.json()
    except Exception as e:
        return {"error": str(e), "cdp_url": CDP_URL}

@app.get("/api/cdp/tabs")
async def cdp_tabs(request: Request):
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401)
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{CDP_URL}/json/list")
            return resp.json()
    except Exception as e:
        return {"error": str(e)}

@app.post("/api/cdp/navigate")
async def cdp_navigate(request: Request):
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401)
    body = await request.json()
    url = body.get("url", "")
    tab_id = body.get("tabId")
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            tabs = await client.get(f"{CDP_URL}/json/list")
            tabs_data = tabs.json()
            if not tabs_data:
                return {"error": "No tabs available"}
            target = tabs_data[0]
            if tab_id:
                for t in tabs_data:
                    if t["id"] == tab_id:
                        target = t
                        break
            ws_url = target.get("webSocketDebuggerUrl", "")
            if not ws_url:
                return {"error": "No WebSocket URL available"}
            import websockets
            async with websockets.connect(ws_url) as ws:
                cmd = {"id": 1, "method": "Page.navigate", "params": {"url": url}}
                await ws.send(json.dumps(cmd))
                result = await asyncio.wait_for(ws.recv(), timeout=10)
                return json.loads(result)
    except Exception as e:
        return {"error": str(e)}

@app.post("/api/cdp/screenshot")
async def cdp_screenshot(request: Request):
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401)
    body = await request.json()
    tab_id = body.get("tabId")
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            tabs = await client.get(f"{CDP_URL}/json/list")
            tabs_data = tabs.json()
            if not tabs_data:
                return {"error": "No tabs"}
            target = tabs_data[0]
            if tab_id:
                for t in tabs_data:
                    if t["id"] == tab_id:
                        target = t
                        break
            ws_url = target.get("webSocketDebuggerUrl", "")
            import websockets
            async with websockets.connect(ws_url) as ws:
                cmd = {"id": 1, "method": "Page.captureScreenshot", "params": {"format": "png"}}
                await ws.send(json.dumps(cmd))
                result = await asyncio.wait_for(ws.recv(), timeout=15)
                data = json.loads(result)
                if "result" in data and "data" in data["result"]:
                    return {"screenshot": data["result"]["data"]}
                return {"error": "No screenshot data", "raw": data}
    except Exception as e:
        return {"error": str(e)}

@app.post("/api/cdp/evaluate")
async def cdp_evaluate(request: Request):
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401)
    body = await request.json()
    expression = body.get("expression", "")
    tab_id = body.get("tabId")
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            tabs = await client.get(f"{CDP_URL}/json/list")
            tabs_data = tabs.json()
            target = tabs_data[0] if tabs_data else None
            if not target:
                return {"error": "No tabs"}
            if tab_id:
                for t in tabs_data:
                    if t["id"] == tab_id:
                        target = t
                        break
            ws_url = target.get("webSocketDebuggerUrl", "")
            import websockets
            async with websockets.connect(ws_url) as ws:
                cmd = {"id": 1, "method": "Runtime.evaluate", "params": {"expression": expression, "returnByValue": True}}
                await ws.send(json.dumps(cmd))
                result = await asyncio.wait_for(ws.recv(), timeout=10)
                return json.loads(result)
    except Exception as e:
        return {"error": str(e)}

@app.get("/api/health")
async def health():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}


LOGIN_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>CDP Harness - Login</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #0f172a; color: #e2e8f0; display: flex; align-items: center; justify-content: center; min-height: 100vh; }
        .login-card { background: #1e293b; border-radius: 12px; padding: 2rem; width: 100%; max-width: 400px; box-shadow: 0 4px 24px rgba(0,0,0,0.3); }
        h1 { text-align: center; margin-bottom: 1.5rem; color: #38bdf8; }
        .form-group { margin-bottom: 1rem; }
        label { display: block; margin-bottom: 0.5rem; font-size: 0.875rem; color: #94a3b8; }
        input { width: 100%; padding: 0.75rem; background: #0f172a; border: 1px solid #334155; border-radius: 8px; color: #e2e8f0; font-size: 1rem; }
        input:focus { outline: none; border-color: #38bdf8; }
        button { width: 100%; padding: 0.75rem; background: #38bdf8; color: #0f172a; border: none; border-radius: 8px; font-size: 1rem; font-weight: 600; cursor: pointer; margin-top: 0.5rem; }
        button:hover { background: #7dd3fc; }
        .subtitle { text-align: center; color: #64748b; margin-bottom: 1rem; font-size: 0.85rem; }
    </style>
</head>
<body>
    <div class="login-card">
        <h1>🖥️ CDP Harness</h1>
        <p class="subtitle">UV Secure Login</p>
        <!-- ERROR -->
        <form method="POST" action="/login">
            <div class="form-group">
                <label>Username</label>
                <input type="text" name="username" required autofocus>
            </div>
            <div class="form-group">
                <label>Password</label>
                <input type="password" name="password" required>
            </div>
            <button type="submit">Sign In</button>
        </form>
    </div>
</body>
</html>"""


DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>CDP Harness - Dashboard</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #0f172a; color: #e2e8f0; }
        .header { background: #1e293b; padding: 1rem 2rem; display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #334155; }
        .header h1 { color: #38bdf8; font-size: 1.25rem; }
        .header a { color: #94a3b8; text-decoration: none; }
        .container { max-width: 1200px; margin: 0 auto; padding: 2rem; }
        .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 1.5rem; margin-bottom: 1.5rem; }
        .card { background: #1e293b; border-radius: 12px; padding: 1.5rem; }
        .card h2 { color: #38bdf8; margin-bottom: 1rem; font-size: 1.1rem; }
        .status-badge { display: inline-block; padding: 0.25rem 0.75rem; border-radius: 20px; font-size: 0.8rem; font-weight: 600; }
        .status-ok { background: #065f46; color: #6ee7b7; }
        .status-err { background: #7f1d1d; color: #fca5a5; }
        pre { background: #0f172a; padding: 1rem; border-radius: 8px; overflow-x: auto; font-size: 0.8rem; max-height: 200px; overflow-y: auto; }
        .input-group { display: flex; gap: 0.5rem; margin-bottom: 1rem; }
        .input-group input { flex: 1; padding: 0.5rem; background: #0f172a; border: 1px solid #334155; border-radius: 8px; color: #e2e8f0; }
        .btn { padding: 0.5rem 1rem; background: #38bdf8; color: #0f172a; border: none; border-radius: 8px; cursor: pointer; font-weight: 600; }
        .btn:hover { background: #7dd3fc; }
        .btn-secondary { background: #475569; color: #e2e8f0; }
        .btn-secondary:hover { background: #64748b; }
        .screenshot-container { text-align: center; }
        .screenshot-container img { max-width: 100%; border-radius: 8px; border: 1px solid #334155; }
        .tabs-list { list-style: none; }
        .tabs-list li { padding: 0.5rem; border-bottom: 1px solid #334155; cursor: pointer; font-size: 0.85rem; }
        .tabs-list li:hover { background: #334155; border-radius: 4px; }
        .tabs-list .tab-url { color: #94a3b8; font-size: 0.75rem; display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        textarea { width: 100%; padding: 0.5rem; background: #0f172a; border: 1px solid #334155; border-radius: 8px; color: #e2e8f0; font-family: monospace; min-height: 80px; resize: vertical; }
        .full-width { grid-column: 1 / -1; }
    </style>
</head>
<body>
    <div class="header">
        <h1>🖥️ CDP Browser Harness</h1>
        <div>
            <span style="color:#94a3b8;margin-right:1rem;">Connected via Tailscale</span>
            <a href="/logout">Logout</a>
        </div>
    </div>
    <div class="container">
        <div class="grid">
            <div class="card">
                <h2>📡 CDP Status</h2>
                <div id="status-content">Loading...</div>
                <button class="btn btn-secondary" onclick="checkStatus()" style="margin-top:0.75rem">Refresh</button>
            </div>
            <div class="card">
                <h2>📑 Browser Tabs</h2>
                <ul class="tabs-list" id="tabs-list">Loading...</ul>
                <button class="btn btn-secondary" onclick="loadTabs()" style="margin-top:0.75rem">Refresh Tabs</button>
            </div>
            <div class="card full-width">
                <h2>🧭 Navigate</h2>
                <div class="input-group">
                    <input type="text" id="nav-url" placeholder="https://example.com" value="https://example.com">
                    <button class="btn" onclick="navigateTo()">Go</button>
                    <button class="btn btn-secondary" onclick="takeScreenshot()">📸 Screenshot</button>
                </div>
            </div>
            <div class="card">
                <h2>💻 Execute JavaScript</h2>
                <textarea id="js-code" placeholder="document.title">document.title</textarea>
                <button class="btn" onclick="evalJS()" style="margin-top:0.5rem">Execute</button>
                <pre id="eval-result" style="margin-top:0.75rem"></pre>
            </div>
            <div class="card screenshot-container">
                <h2>📸 Screenshot</h2>
                <img id="screenshot-img" src="" alt="No screenshot yet" style="display:none">
                <p id="screenshot-placeholder">Click Screenshot to capture</p>
            </div>
        </div>
    </div>
    <script>
        let selectedTabId = null;

        async function checkStatus() {
            try {
                const r = await fetch('/api/cdp/status');
                const d = await r.json();
                const el = document.getElementById('status-content');
                if (d.error) {
                    el.innerHTML = '<span class="status-badge status-err">Disconnected</span><pre>' + JSON.stringify(d, null, 2) + '</pre>';
                } else {
                    el.innerHTML = '<span class="status-badge status-ok">Connected</span><pre>' + JSON.stringify(d, null, 2) + '</pre>';
                }
            } catch (e) {
                document.getElementById('status-content').innerHTML = '<span class="status-badge status-err">Error</span><pre>' + e.message + '</pre>';
            }
        }

        async function loadTabs() {
            try {
                const r = await fetch('/api/cdp/tabs');
                const d = await r.json();
                const el = document.getElementById('tabs-list');
                if (d.error) {
                    el.innerHTML = '<li>' + d.error + '</li>';
                    return;
                }
                el.innerHTML = d.map(t => '<li onclick="selectTab(\''+t.id+'\')"><strong>' + (t.title || 'Untitled') + '</strong><span class="tab-url">' + (t.url || '') + '</span></li>').join('');
            } catch(e) {
                document.getElementById('tabs-list').innerHTML = '<li>Error: ' + e.message + '</li>';
            }
        }

        function selectTab(id) {
            selectedTabId = id;
            document.querySelectorAll('.tabs-list li').forEach(li => li.style.background = '');
            event.currentTarget.style.background = '#334155';
        }

        async function navigateTo() {
            const url = document.getElementById('nav-url').value;
            const r = await fetch('/api/cdp/navigate', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({url, tabId: selectedTabId})});
            const d = await r.json();
            if (d.error) alert('Error: ' + d.error);
            else { loadTabs(); setTimeout(takeScreenshot, 2000); }
        }

        async function takeScreenshot() {
            document.getElementById('screenshot-placeholder').textContent = 'Capturing...';
            const r = await fetch('/api/cdp/screenshot', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({tabId: selectedTabId})});
            const d = await r.json();
            if (d.screenshot) {
                const img = document.getElementById('screenshot-img');
                img.src = 'data:image/png;base64,' + d.screenshot;
                img.style.display = 'block';
                document.getElementById('screenshot-placeholder').style.display = 'none';
            } else {
                document.getElementById('screenshot-placeholder').textContent = 'Error: ' + (d.error || 'Unknown');
            }
        }

        async function evalJS() {
            const expression = document.getElementById('js-code').value;
            const r = await fetch('/api/cdp/evaluate', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({expression, tabId: selectedTabId})});
            const d = await r.json();
            document.getElementById('eval-result').textContent = JSON.stringify(d, null, 2);
        }

        checkStatus();
        loadTabs();
    </script>
</body>
</html>"""

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8080"))
    uvicorn.run(app, host="0.0.0.0", port=port)
