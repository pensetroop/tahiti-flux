# app.py — FLUX-SCHNELL (Replicate) — minimal, UTF-8 safe, texte->image + Framer (CORS + iframe)
import os, sys
from flask import Flask, request, jsonify
from flask_cors import CORS
from werkzeug.exceptions import HTTPException
import replicate

# ---- UTF-8 safe (Windows)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")
except Exception:
    pass

app = Flask(__name__)

# ---- CORS: OK pour Framer + wildcard (regex de ressource sûre)
FRAMER_ORIGINS = ["https://*.framer.app", "https://*.framer.website"]
CORS(
    app,
    resources={r"/.*": {"origins": FRAMER_ORIGINS + ["*"]}},
    methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
    expose_headers=["Content-Type"],
    supports_credentials=False,
)

# ---- Autoriser l’embed en <iframe> depuis Framer (CSP)
@app.after_request
def add_frame_headers(resp):
    resp.headers["Content-Security-Policy"] = (
        "frame-ancestors 'self' https://*.framer.app https://*.framer.website"
    )
    # On retire X-Frame-Options si injecté par un middleware
    resp.headers.pop("X-Frame-Options", None)
    return resp

# ---- Config / Clients
REPLICATE_API_TOKEN = os.environ.get("REPLICATE_API_TOKEN", "")
MODEL_SLUG = (os.environ.get("SIMPLE_MODEL") or "black-forest-labs/flux-schnell").split(":")[0]
client = replicate.Client(api_token=REPLICATE_API_TOKEN)

# ---- Helpers
def merge_data():
    data = request.get_json(silent=True) or {}
    data.update(request.form.to_dict(flat=True))
    return data

def first_url(out):
    def pick(x):
        if isinstance(x, str) and x.startswith("http"): return x
        if hasattr(x, "url"): return x.url
        if isinstance(x, dict):
            for v in x.values():
                u = pick(v)
                if u: return u
        if isinstance(x, (list, tuple)):
            for v in x:
                u = pick(v); 
                if u: return u
        return None
    return pick(out)

# ---- Routes
@app.get("/")
def home():
    return jsonify({"ok": True, "service": "tahiti-flux", "model": MODEL_SLUG,
                    "endpoints": {"/health": "GET", "/generate": "POST"}}), 200

@app.get("/health")
def health():
    return jsonify({"ok": True, "has_token": bool(REPLICATE_API_TOKEN), "model": MODEL_SLUG}), 200

@app.errorhandler(Exception)
def on_error(e):
    code = e.code if isinstance(e, HTTPException) else 500
    msg = str(e)
    try: msg = msg.encode("utf-8", "backslashreplace").decode("utf-8")
    except Exception: pass
    return jsonify({"ok": False, "type": e.__class__.__name__, "error": msg}), code

# ---- Génération texte -> image (OPTIONS pour preflight CORS)
@app.route("/generate", methods=["POST", "OPTIONS"])
def generate():
    if request.method == "OPTIONS":
        return ("", 204)

    if not REPLICATE_API_TOKEN:
        return jsonify({"ok": False, "error": "Missing REPLICATE_API_TOKEN"}), 500

    data = merge_data()
    prompt = str(data.get("prompt", "") or "").strip()
    if not prompt:
        return jsonify({"ok": False, "error": "Missing 'prompt'"}), 400

    aspect_ratio = str(data.get("aspect_ratio", "1:1") or "1:1").strip()
    mp           = str(data.get("mp", "1") or "1").strip()
    fmt          = str(data.get("format", "webp") or "webp").strip()
    fast_flag    = str(data.get("fast", "1")).lower() in ["1","true","yes","on"]
    safety_flag  = str(data.get("disable_safety_checker", "0")).lower() in ["1","true","yes","on"]

    n_raw       = data.get("n", 1)
    quality_raw = data.get("quality", 80)
    seed_raw    = str(data.get("seed", "") or "").strip()

    try:    n = max(1, min(4, int(n_raw)))
    except: n = 1
    try:    quality = max(0, min(100, int(quality_raw)))
    except: quality = 80
    seed = int(seed_raw) if seed_raw.isdigit() else None

    if "image" in request.files:
        return jsonify({"ok": False, "error": "text-to-image only"}), 400

    inputs = {
        "prompt": prompt,
        "go_fast": fast_flag,
        "megapixels": mp,
        "num_outputs": n,
        "aspect_ratio": aspect_ratio,
        "output_format": fmt,
        "output_quality": quality,
        "disable_safety_checker": safety_flag,
    }
    if seed is not None:
        inputs["seed"] = seed

    try:
        out = client.run(MODEL_SLUG, input=inputs)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

    url = first_url(out)
    if not url:
        return jsonify({"ok": False, "error": "No image URL from model", "raw": out}), 502
    return jsonify({"ok": True, "image_url": url, "model": MODEL_SLUG}), 200

# Local only
if __name__ == "__main__":
    app.run(host="127.0.0.1", port=10000, debug=False, use_reloader=False)

