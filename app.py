import os
import re
import json
import time
from fastapi import FastAPI, UploadFile, File, Form
from fastapi.responses import FileResponse, JSONResponse
from dotenv import load_dotenv
from sarvamai import SarvamAI
from sarvamai.core.api_error import ApiError
import uvicorn

load_dotenv()
key = os.environ.get("SARVAM_API_KEY", "").strip()
if key == "":
    raise SystemExit("SARVAM_API_KEY is empty, paste your key in .env")

client = SarvamAI(api_subscription_key=key)
app = FastAPI()
chat_model = "sarvam-105b-conversations"
policy = open("policy.md", encoding="utf-8").read()
sessions = {}
need = ["name", "occupation", "monthly_income", "loan_amount", "purpose"]

langs = {
    "hi-IN": ["Hindi", "ritu_hi_banking"],
    "en-IN": ["English", "simran_en_customer"],
    "bn-IN": ["Bengali", "arnab_bn_conversation"],
    "mr-IN": ["Marathi", "nilesh_mr_conversation"],
    "ta-IN": ["Tamil", "gokul_ta_narration"],
    "te-IN": ["Telugu", "kavitha_te_conversation"],
}

doc_schema = {
    "type": "object",
    "properties": {
        "document_type": {"type": "string", "description": "Kind of document, for example bank statement, salary slip, platform earnings statement, GST certificate, Aadhaar, Voter ID, PAN"},
        "holder_name": {"type": "string", "description": "Full name of the person the document belongs to"},
        "monthly_income": {"type": "number", "description": "Average or latest monthly net income or earnings in INR if the document shows it, otherwise leave empty"},
        "period": {"type": "string", "description": "Time period the document covers, for example Jan 2026 to Mar 2026"},
        "employer_or_platform": {"type": "string", "description": "Employer, business or platform name shown on the document"},
    },
}


def sess(sid):
    if sid not in sessions:
        sessions[sid] = {"hist": [], "log": [], "fields": {}, "docs": [], "cited": [], "escalate": False}
    return sessions[sid]


def num(x):
    t = re.sub(r"[^0-9.]", "", str(x))
    if t == "" or t == ".":
        return None
    try:
        return float(t)
    except ValueError:
        return None


def prompt(s, lang):
    p = "You are a phone-based loan pre-qualification agent for a bank in India. The caller may be on a basic phone, so keep every reply to 1 to 3 short spoken sentences in plain words, no lists, no markdown.\n"
    p += "Reply in " + langs[lang][0] + ", written in that language's own script. Common English words are fine.\n"
    p += "Find out the caller's name, occupation (shop or business owner, gig or platform worker, other), monthly income, loan amount needed, purpose, and any existing EMIs. Ask one question at a time.\n"
    p += "Answer questions about loan products only from the POLICY below. If the policy does not cover something, say you will connect the caller to a loan officer and set escalate to true. Never guess figures. Never approve or reject a loan and never promise approval, the final decision is the loan officer's.\n"
    p += "When you know enough, say which product fits and what it needs, based only on the policy, then ask the caller to send income proof as a photo through a smartphone.\n"
    p += "If the caller's message is (call connected), greet them briefly as the bank's loan assistant and ask how you can help. If a message starts with ( it is a system note, not something the caller said.\n"
    p += 'Output ONLY one JSON object and nothing else: {"reply": "what you say aloud", "cited": ["policy clause ids you relied on, like UM-3"], "fields": {"name": "", "occupation": "", "monthly_income": 0, "loan_amount": 0, "purpose": "", "existing_emi": 0}, "escalate": false}. In fields include only values the caller gave or changed this turn, amounts as plain numbers in INR. The spoken reply must not contain clause ids.\n\n'
    p += "POLICY:\n" + policy
    if len(s["docs"]) > 0:
        p += "\n\nVERIFIED DOCUMENT DATA (read from documents the caller uploaded). Use it to confirm what the caller said, and mention gently if a figure differs:\n"
        for d in s["docs"]:
            p += json.dumps(d["fields"], ensure_ascii=False) + "\n"
    return p


def parse(raw):
    a = raw.find("{")
    b = raw.rfind("}")
    if a >= 0 and b > a:
        try:
            d = json.loads(raw[a:b + 1])
            if isinstance(d, dict) and "reply" in d:
                return d
        except ValueError:
            pass
    return {"reply": raw.strip(), "cited": [], "fields": {}, "escalate": False}


def summary(s):
    f = s["fields"]
    missing = []
    for k in need:
        if k not in f:
            missing.append(k)
    if len(s["docs"]) == 0:
        missing.append("income proof")
    flags = []
    for d in s["docs"]:
        df = d["fields"] or {}
        hn = str(df.get("holder_name") or "").strip().lower()
        n = str(f.get("name") or "").strip().lower()
        if hn != "" and n != "" and n not in hn and hn not in n:
            flags.append("name on document does not match stated name")
        di = num(df.get("monthly_income"))
        si = num(f.get("monthly_income"))
        if di and si and abs(di - si) / si > 0.15:
            flags.append("income on document differs from stated income by more than 15%")
    if s["escalate"]:
        flags.append("question not covered by policy, needs loan officer")
    status = "ready_for_officer"
    if len(flags) > 0:
        status = "needs_officer_review"
    elif len(missing) > 0:
        status = "in_progress"
    return {"status": status, "fields": f, "docs": s["docs"], "cited": s["cited"], "missing": missing, "flags": flags, "log": s["log"]}


def err(e):
    return JSONResponse({"error": str(e.status_code) + ": " + str(e.body)}, status_code=502)


@app.get("/")
def home():
    return FileResponse("index.html")


@app.get("/api/summary")
def get_summary(sid: str):
    return summary(sess(sid))


@app.post("/api/turn")
def turn(sid: str = Form(...), lang: str = Form("hi-IN"), text: str = Form(""), audio: UploadFile = File(None)):
    if lang not in langs:
        lang = "hi-IN"
    s = sess(sid)
    try:
        heard = text
        if audio is not None:
            r = client.speech_to_text.transcribe(
                file=("audio.wav", audio.file.read(), "audio/wav"),
                model="saaras:v4",
                mode="transcribe",
                language_code=lang,
            )
            heard = r.transcript or ""
        if heard.strip() == "":
            return {"heard": "", "reply": "", "audio": None, "summary": summary(s)}
        s["hist"].append({"role": "user", "content": heard})
        s["log"].append({"who": "caller", "text": heard})
        msgs = [{"role": "system", "content": prompt(s, lang)}] + s["hist"][-20:]
        r = client.chat.completions(model=chat_model, messages=msgs, reasoning_effort=None, temperature=0.3, max_tokens=800)
        raw = r.choices[0].message.content or ""
        d = parse(raw)
        s["hist"].append({"role": "assistant", "content": raw})
        for k, v in (d.get("fields") or {}).items():
            if v is not None and v != "" and v != 0:
                s["fields"][k] = v
        for c in d.get("cited") or []:
            if c not in s["cited"]:
                s["cited"].append(c)
        if d.get("escalate"):
            s["escalate"] = True
        reply = str(d.get("reply") or "").strip()
        if reply == "":
            reply = "Sorry, could you say that again?"
        s["log"].append({"who": "agent", "text": reply})
        t = client.text_to_speech.convert(text=reply[:2000], language_code=lang, model="bulbul:v4-flash", speaker=langs[lang][1])
        return {"heard": heard, "reply": reply, "audio": t.audios[0], "summary": summary(s)}
    except ApiError as e:
        return err(e)


@app.post("/api/doc")
def doc(sid: str = Form(...), file: UploadFile = File(...)):
    s = sess(sid)
    try:
        job = client.doc_ai.extract(
            file=[(file.filename, file.file.read(), file.content_type)],
            schema=json.dumps(doc_schema),
            output_format="json",
        )
        st = None
        for i in range(40):
            st = client.doc_ai.get_status(job_id=job.job_id)
            if st.status.lower() in ("completed", "partially_completed", "failed", "rejected"):
                break
            time.sleep(2)
        if st is None or st.status.lower() not in ("completed", "partially_completed"):
            return JSONResponse({"error": "document job did not complete, status " + str(getattr(st, "status", "unknown"))}, status_code=502)
        res = client.doc_ai.get_results(job_id=job.job_id)
        out = res.result
        if hasattr(out, "model_dump"):
            out = out.model_dump()
        s["docs"].append({"name": file.filename, "fields": out})
        return {"fields": out, "summary": summary(s)}
    except ApiError as e:
        return err(e)


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
