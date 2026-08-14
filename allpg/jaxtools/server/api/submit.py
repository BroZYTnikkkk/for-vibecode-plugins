from http.server import BaseHTTPRequestHandler
import json, os, base64, urllib.request, urllib.error, re

TOKEN = os.environ["GITHUB_TOKEN"]
REPO = os.environ["GITHUB_REPO"]
FILE_PATH = os.environ["GITHUB_FILE"]
BRANCH = os.environ.get("GITHUB_BRANCH", "main")

class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        self.send_response(200)
        self.send_header("Content-type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            self.wfile.write(json.dumps({"ok": False, "error": "invalid json"}).encode())
            return
        
        uid = str(data.get("uid", ""))
        text = data.get("text", "")
        emoji_id = data.get("emoji_id", "")
        
        if not uid or not text or not emoji_id:
            self.wfile.write(json.dumps({"ok": False, "error": "missing fields"}).encode())
            return
        
        result = append_to_badge(uid, text, emoji_id)
        self.wfile.write(json.dumps(result).encode())
    
    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

def append_to_badge(uid, text, emoji_id):
    api_url = f"https://api.github.com/repos/{REPO}/contents/{FILE_PATH}"
    headers = {
        "Authorization": f"Bearer {TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "jaxtools-server"
    }
    
    req = urllib.request.Request(api_url, headers=headers, method="GET")
    
    try:
        resp = urllib.request.urlopen(req)
        existing = json.loads(resp.read())
        content = base64.b64decode(existing["content"]).decode("utf-8")
        sha = existing["sha"]
    except urllib.error.HTTPError as e:
        if e.code == 404:
            content = "# для верифки\n\n| user_id | custom text | emoji_id |\n|---------|-------------|----------|\n"
            sha = None
        else:
            return {"ok": False, "error": f"github get failed: {e.code}"}
    
    new_line = f"| {uid} | {text} | {emoji_id} |"
    
    if uid in content:
        lines = content.split("\n")
        for i, line in enumerate(lines):
            if line.startswith(f"| {uid} "):
                lines[i] = new_line
                break
        content = "\n".join(lines)
        message = f"Update {uid}"
    else:
        content = content.rstrip("\n") + "\n" + new_line + "\n"
        message = f"Add {uid}"
    
    new_content = base64.b64encode(content.encode("utf-8")).decode()
    payload = {
        "message": message,
        "content": new_content,
        "branch": BRANCH
    }
    if sha:
        payload["sha"] = sha
    
    req = urllib.request.Request(
        api_url,
        data=json.dumps(payload).encode(),
        headers={**headers, "Content-Type": "application/json"},
        method="PUT"
    )
    
    try:
        urllib.request.urlopen(req)
        return {"ok": True}
    except urllib.error.HTTPError as e:
        return {"ok": False, "error": f"github put failed: {e.code}"}
