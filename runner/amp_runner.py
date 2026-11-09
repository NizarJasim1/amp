"""amp_runner.py - runs the study automatically through model APIs (Track B), exactly as plan.csv says.

Track A (the app, by hand) stays the ecological check: "does it work where people actually use it". Track B
gives n in the hundreds, no human fatigue or order effects, raw transcripts, token costs, and other model
families. Both tracks write the same answer files, so grade.py reads either; analysis/compare_tracks.py
measures how well they agree on the seeds run both ways.

    python amp_runner.py --kit ../kit --runs runs_api --config providers.json [--only R001,R002] [--tier P] [--limit 5]
    python amp_runner.py --kit ../kit --runs runs_mock --config providers.mock.json      (offline pipeline test)

Isolation (v6.7): real API runs need the sandbox to run as a SEPARATE OS user (start the runner as root with
--sandbox-user, as the Docker image does). Before the first run the runner probes what model-written code could
read; it refuses to start if the runner's environment (API key), the answer key, or other runs are readable.
--unsafe-shared-uid overrides this for a throwaway machine with nothing to lose. A model's 'verifier' must not be
one of the models compared in the plan (it would feed one arm with the other arm's answers).

Every model gets the SAME tool: one persistent Python session (sandbox.py). That equalises tools across model
families, which the app cannot do. Text attachments (.md/.txt) are placed in the message; .py files are placed
only in the sandbox's uploads folder (the protocol loads them from there).

Standard library only. API keys come from environment variables named in the config, never from files.
SECURITY: model-written code runs on this machine - use a throwaway VM or the Docker image (see Dockerfile).
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sandbox import Sandbox, rewrite  # noqa: E402

TOOL_DESC = ("Run Python code in a persistent session (variables, imports and functions survive between calls). "
             "Attached files are in /mnt/user-data/uploads; save files to /mnt/user-data/outputs. Print what you need to see.")
TOOL_DESC_VERIFIER = TOOL_DESC + (" To get an INDEPENDENT second opinion from a DIFFERENT model, make the FIRST line "
             "of your code exactly '#SECOND_OPINION' and put your question on the following lines; the result is that "
             "other model's text (use it as a source='model:B' check, never as your own). To have ideas or a plan attacked "
             "by that other model in a FRESH context, make the code exactly pkt['runner'] from amp_lab's pool.packet(...); "
             "the critic's reply is saved to /mnt/user-data/uploads/critic_<packet>.txt for pool.ingest(...).")
FINAL_MSG = None   # the runner extracts the final JSON blocks itself; no extra "merge" turn is sent


# ============================================================================ providers
def _post(url, headers, body, retries=8):
    data = json.dumps(body).encode()
    for k in range(retries):
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=900) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            code = e.code
            msg = e.read().decode(errors="replace")[:500]
            if code in (408, 409, 429, 500, 502, 503, 504, 529) and k < retries - 1:
                time.sleep(min(120, 5 * 2 ** k))
                continue
            raise RuntimeError(f"HTTP {code}: {msg}")
        except (urllib.error.URLError, TimeoutError) as e:
            if k < retries - 1:
                time.sleep(min(120, 5 * 2 ** k))
                continue
            raise RuntimeError(repr(e))


class Anthropic:
    def __init__(self, cfg):
        self.cfg = cfg
        self.key = os.environ.get(cfg.get("key_env", "ANTHROPIC_API_KEY"), "")
        self.url = cfg.get("base_url", "https://api.anthropic.com") + "/v1/messages"

    def tool(self):
        return [{"name": "python", "description": TOOL_DESC_VERIFIER if self.cfg.get("verifier") else TOOL_DESC,
                 "input_schema": {"type": "object", "properties": {"code": {"type": "string"}}, "required": ["code"]}}]

    def user(self, text, cache=False):
        block = {"type": "text", "text": text}
        if cache:
            block["cache_control"] = {"type": "ephemeral"}
        return {"role": "user", "content": [block]}

    def call(self, messages):
        body = {"model": self.cfg["model"], "max_tokens": self.cfg.get("max_tokens", 16000), "tools": self.tool(),
                "messages": messages, **self.cfg.get("extra", {})}
        r = _post(self.url, {"x-api-key": self.key, "anthropic-version": self.cfg.get("version", "2023-06-01"),
                             "content-type": "application/json"}, body)
        text = "".join(b.get("text", "") for b in r["content"] if b["type"] == "text")
        calls = [(b["id"], b["input"].get("code", "")) for b in r["content"] if b["type"] == "tool_use"]
        u = r.get("usage", {})
        usage = {"in": u.get("input_tokens", 0), "out": u.get("output_tokens", 0),
                 "cache_write": u.get("cache_creation_input_tokens", 0) or 0, "cache_read": u.get("cache_read_input_tokens", 0) or 0}
        return {"assistant": {"role": "assistant", "content": r["content"]}, "text": text, "calls": calls,
                "stop": r.get("stop_reason"), "usage": usage}

    def results(self, outs):
        return [{"role": "user", "content": [{"type": "tool_result", "tool_use_id": i, "content": o} for i, o in outs]}]


class OpenAICompat:
    """Any OpenAI-compatible chat-completions endpoint (open models served by vLLM, OpenRouter, Together, ...)."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.key = os.environ.get(cfg.get("key_env", "OPENAI_API_KEY"), "")
        self.url = cfg["base_url"].rstrip("/") + "/chat/completions"

    def user(self, text, cache=False):
        return {"role": "user", "content": text}

    def call(self, messages):
        body = {"model": self.cfg["model"], "max_tokens": self.cfg.get("max_tokens", 16000), "messages": messages,
                "tools": [{"type": "function", "function": {"name": "python", "description": TOOL_DESC,
                                                            "parameters": {"type": "object", "properties": {"code": {"type": "string"}},
                                                                           "required": ["code"]}}}], **self.cfg.get("extra", {})}
        r = _post(self.url, {"Authorization": f"Bearer {self.key}", "content-type": "application/json"}, body)
        m = r["choices"][0]["message"]
        calls = []
        for tc in m.get("tool_calls") or []:
            try:
                code = json.loads(tc["function"]["arguments"]).get("code", "")
            except Exception:
                code = ""
            calls.append((tc["id"], code))
        u = r.get("usage", {})
        msg = {"role": "assistant", "content": m.get("content") or ""}
        if m.get("tool_calls"):
            msg["tool_calls"] = m["tool_calls"]
        return {"assistant": msg, "text": m.get("content") or "", "calls": calls,
                "stop": "tool_use" if calls else r["choices"][0].get("finish_reason"),
                "usage": {"in": u.get("prompt_tokens", 0), "out": u.get("completion_tokens", 0), "cache_write": 0, "cache_read": 0}}

    def results(self, outs):
        return [{"role": "tool", "tool_call_id": i, "content": o} for i, o in outs]


class Mock:
    """Offline scripted model: one tool call per part, then a well-formed answer. Tests the whole pipeline."""

    def __init__(self, cfg):
        self.cfg, self.n = cfg, 0

    def user(self, text, cache=False):
        return {"role": "user", "content": text}

    def call(self, messages):
        last = messages[-1]
        self.n += 1
        if last.get("role") == "user" and isinstance(last.get("content"), str) and "independent hostile reviewer" in last["content"]:
            pid = re.search(r"packet id: (\w+)", last["content"]).group(1)
            ids = re.findall(r"^(C\d+)\. ", last["content"], re.M)
            rv = [{"id": c, "verdict": "KILL" if k == 0 else "SURVIVE", "failure_case": "mock case: input of size 0",
                   "test": "run it on the empty input", "confidence": 0.6} for k, c in enumerate(ids)]
            text = "```json\n" + json.dumps({"packet": pid, "reviews": rv}) + "\n```"
            return {"assistant": {"role": "assistant", "content": text}, "text": text, "calls": [], "stop": "end_turn",
                    "usage": {"in": 50, "out": 50, "cache_write": 0, "cache_read": 0}}
        if last.get("role") == "user" and isinstance(last.get("content"), str):
            body = last["content"]
            if "I1." in body and "PART5.json" in body:
                code = ("import json; json.dump({'I1': 'def place(x, bins):\\n    return len(bins)\\n'}, "
                        "open('/mnt/user-data/outputs/PART5.json', 'w')); print('saved')")
            else:
                code = "print(sum(range(10)))"
            return {"assistant": {"role": "assistant", "content": "", "tool_calls": [{"id": f"m{self.n}"}]}, "text": "",
                    "calls": [(f"m{self.n}", code)], "stop": "tool_use", "usage": {"in": 100, "out": 20, "cache_write": 0, "cache_read": 0}}
        items = {}
        joined = " ".join(m["content"] for m in messages if m.get("role") == "user" and isinstance(m.get("content"), str))
        part = joined[joined.rfind("Final answer"):]
        for k in re.findall(r'"([QGKT]\d)"', part)[:12]:
            items[k] = "45"
        items["_conf"] = {k: 0.5 for k in items}
        text = "log: mock\n```json\n" + json.dumps(items) + "\n```"
        return {"assistant": {"role": "assistant", "content": text}, "text": text, "calls": [], "stop": "end_turn",
                "usage": {"in": 200, "out": 50, "cache_write": 0, "cache_read": 0}}

    def results(self, outs):
        return [{"role": "tool", "tool_call_id": i, "content": o} for i, o in outs]


PROVIDERS = {"anthropic": Anthropic, "openai": OpenAICompat, "mock": Mock}


# ============================================================================ independent critic
def _lab(kit=""):
    """amp_lab from the kit (what the model got) or from src: the critic text has ONE source."""
    import importlib.util
    here = os.path.dirname(os.path.abspath(__file__))
    for p in (os.path.join(kit, "protocols", "amp_lab.py"), os.path.join(here, "..", "src", "amp_lab.py")):
        if os.path.exists(p):
            spec = importlib.util.spec_from_file_location("amp_lab_critic", p)
            m = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(m)
            return m
    raise FileNotFoundError("amp_lab.py not found")


class LiveLog:
    """#LIVE <target>: the RUNNER executes a configured live target (config "live_targets": {name: {"cmd": [...]}})
    and logs its output. The receipt 'id:sha256:mac' is signed with a key that exists only in this process, never in
    the sandbox, so text the model writes itself cannot obtain one. This is what makes provenance='live' a fact
    instead of a word (amp_lab.provenance_check in the run, amp_lab.attest_certificate after it)."""

    def __init__(self, targets, work, timeout=60):
        self.key, self.targets, self.work, self.timeout, self.texts = secrets.token_bytes(32), targets or {}, work, timeout, {}

    def mac(self, rid, sha):
        return hmac.new(self.key, f"{rid}:{sha}".encode(), hashlib.sha256).hexdigest()[:32]

    def ok(self, receipt):
        p = str(receipt or "").strip().split(":")
        return (len(p) == 3 and p[0] in self.texts and hmac.compare_digest(self.mac(p[0], p[1]), p[2])
                and hashlib.sha256(self.texts[p[0]].encode("utf-8")).hexdigest() == p[1])

    def run(self, code):
        head, _, stdin = code.lstrip().partition("\n")
        name = head[len("#LIVE"):].strip()
        t = self.targets.get(name)
        if t is None:
            return f"[no live target {name!r}; configured: {sorted(self.targets) or 'none'}]"
        try:
            r = subprocess.run(t["cmd"], input=stdin, capture_output=True, text=True, timeout=t.get("timeout", self.timeout))
            out = r.stdout + r.stderr
        except Exception as e:  # noqa: BLE001
            return f"[live target {name!r} failed: {e!r}]"
        rid = f"L{len(self.texts) + 1}"
        with open(os.path.join(self.work, "uploads", f"live_{rid}.txt"), "w", encoding="utf-8", newline="") as f:
            f.write(out)
        self.texts[rid] = out
        sha = hashlib.sha256(out.encode("utf-8")).hexdigest()
        rc = f"{rid}:{sha}:{self.mac(rid, sha)}"
        return (f"[live output of {name!r}, logged by the runner at /mnt/user-data/uploads/live_{rid}.txt]\n"
                f"seal it: ev.source_file('/mnt/user-data/uploads/live_{rid}.txt', provenance='live', receipt='{rc}')\n"
                + out[:8000])


def attest_run(lab, out_dir, given_texts, live):
    """After the run, re-check provenance with the runner's OWN material: problem files it delivered, outputs it
    logged, receipts it signed. Nothing the model declared is taken on its word."""
    rep = {"track": "B", "registry": None, "evidence": None}
    for name, key, fn in (("amp_cert.json", "registry", lab.attest_certificate), ("amp_evidence.json", "evidence", lab.attest_evidence)):
        p = os.path.join(out_dir, name)
        if os.path.exists(p):
            try:
                rep[key] = fn(json.load(open(p, encoding="utf-8")), given_texts, live.texts, live.ok)
            except Exception as e:  # noqa: BLE001  a malformed certificate proves nothing
                rep[key] = {"intact": False, "proven": [], "error": repr(e)}
    return rep


def critic_call(code, vprov, vcfg, author_cfg, save_dir, kit=""):
    """#CRITIC hook: rebuild the sealed prompt from the packet (author framing cannot leak in), send it to a
    DIFFERENT model in a brand-new conversation, save the raw reply. Returns the tool output text."""
    if vprov is None:
        return ("[no independent critic is configured for this run. A review you write yourself is source='self' "
                "and never makes an idea ready. Answer the strongest attacks you can, and say the review was not independent.]")
    if vcfg.get("model") and vcfg.get("model") == author_cfg.get("model"):
        return "[critic refused: the critic model is the same model as the author. Configure a different 'verifier'.]"
    try:
        pkt = json.loads(code.split("\n", 1)[1])
        pkt = {k: pkt[k] for k in ("packet", "kind", "brief", "items")}
    except Exception as e:  # noqa: BLE001
        return f"[critic packet unreadable ({e!r}); send exactly pkt['runner'] from pool.packet(...)]"
    vr = vprov.call([vprov.user(_lab(kit).critic_prompt(pkt))])
    name = f"critic_{re.sub(r'[^0-9a-f]', '', str(pkt['packet']))[:12]}.txt"
    open(os.path.join(save_dir, name), "w", encoding="utf-8").write(vr["text"])
    src = f"model:{vcfg.get('model') or vcfg.get('provider')}"
    return (f"[critic reply from a DIFFERENT model in a fresh context, saved to /mnt/user-data/uploads/{name}. "
            f"Ingest: pool.ingest(open('/mnt/user-data/uploads/{name}').read(), source='{src}')]\n" + vr["text"][:3000])


# ============================================================================ one run
def last_json(text):
    blocks = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    for b in reversed(blocks):
        try:
            return json.loads(b)
        except json.JSONDecodeError:
            continue
    return {}


def _private_dirs(runs, sandbox_user):
    """With a separate sandbox user, runs/ and runs/_work/ are traversable but not listable, and every result file
    the runner writes is private to it (umask 077, set in main): the sandbox reaches only its own work folder."""
    os.makedirs(os.path.join(runs, "_work"), exist_ok=True)
    if sandbox_user:
        for d in (runs, os.path.join(runs, "_work")):
            os.chmod(d, 0o711)


def feedback_file(runs, model):
    """Graded feedback for FULL runs of ONE model (grade.py writes amp_feedback_<model>.json): a FULL@48 chain never
    sees outcomes of FULL@55 or of any other condition."""
    for d in (runs, os.path.join(runs, "results")):
        p = os.path.join(d, f"amp_feedback_{model}.json")
        if os.path.exists(p):
            return p
    return None


def run_one(row, kit, runs, cfg_all, sandbox_user=None):
    rid = row["run_id"]
    mcfg = cfg_all["models"][row["model"]]
    lim = cfg_all.get("limits", {})
    prov = PROVIDERS[mcfg["provider"]](mcfg)
    vcfg = cfg_all["models"].get(mcfg.get("verifier")) if mcfg.get("verifier") else None
    vprov = PROVIDERS[vcfg["provider"]](vcfg) if vcfg else None    # a DIFFERENT model, for cross-source checks
    _private_dirs(runs, sandbox_user)
    work = os.path.abspath(os.path.join(runs, "_work", rid))
    shutil.rmtree(work, ignore_errors=True)
    seed = row["seed"]
    names = [f"PART{i}.txt" for i in range(1, 7) if os.path.exists(os.path.join(kit, "tests", f"T{seed}", f"PART{i}.txt"))]
    parts = [open(os.path.join(kit, "tests", f"T{seed}", n), encoding="utf-8").read() for n in names]   # PART6 = optional external anchor
    given_texts = [rewrite(p, work) for p in parts]          # the problem files EXACTLY as delivered to uploads
    sb = Sandbox(work, timeout=lim.get("tool_timeout", 300),
                 env={"AMP_TRACK": "B", "AMP_GIVEN_SHA256": ",".join(hashlib.sha256(t.encode("utf-8")).hexdigest()
                                                                    for t in given_texts)},
                 user=sandbox_user)
    live = LiveLog(cfg_all.get("live_targets"), work, timeout=lim.get("tool_timeout", 300))
    attach = row["attach_first"].split()
    inline = []
    for rel in attach:
        src = os.path.join(kit, rel)
        txt = open(src, encoding="utf-8").read()
        open(os.path.join(work, "uploads", os.path.basename(rel)), "w", encoding="utf-8").write(rewrite(txt, work))
        if not rel.endswith(".py") and "/PART" not in rel:
            inline.append(f'<file name="{os.path.basename(rel)}">\n{txt}\n</file>')
        elif rel.endswith(".py"):
            inline.append(f'<file name="{os.path.basename(rel)}">(Python file, available at /mnt/user-data/uploads/{os.path.basename(rel)})</file>')
    if live.targets:
        inline.append("<note>Live targets the runner can query for you (make the first code line '#LIVE <name>' and put "
                      f"the input on the next lines; the output comes back with a receipt): {sorted(live.targets)}</note>")
    if row.get("memory_from"):
        mp = os.path.join(runs, f"{row['memory_from']}_memory.json")
        if os.path.exists(mp):
            shutil.copy(mp, os.path.join(work, "uploads", "amp_memory.json"))
            inline.append('<file name="amp_memory.json">(memory file, available in /mnt/user-data/uploads)</file>')
        fb = feedback_file(runs, row["model"])
        if fb and row["condition"] == "FULL":
            shutil.copy(fb, os.path.join(work, "uploads", "amp_feedback.json"))
            inline.append('<file name="amp_feedback.json">(graded feedback, available in /mnt/user-data/uploads)</file>')
    messages, merged, usage, tool_calls, log = [], {}, {"in": 0, "out": 0, "cache_write": 0, "cache_read": 0}, 0, []
    t0 = time.time()
    tlog = open(os.path.join(runs, f"{rid}.transcript.jsonl"), "w", encoding="utf-8")
    try:
        for i, part in enumerate(parts, 1):
            with open(os.path.join(work, "uploads", names[i - 1]), "w", encoding="utf-8") as f:
                f.write(given_texts[i - 1])                  # sealable as provenance='given' (ev.source_file)
            if i == 1:
                text = row["opening"] + "\n\n" + "\n\n".join(inline) + f'\n\n<file name="PART1.txt">\n{part}\n</file>'
                messages.append(prov.user(text, cache=True))
            else:
                messages.append(prov.user(f'<file name="PART{i}.txt">\n{part}\n</file>'))
            calls_here, conts = 0, 0
            while True:
                r = prov.call(messages)
                for k in usage:
                    usage[k] += r["usage"][k]
                messages.append(r["assistant"])
                tlog.write(json.dumps({"part": i, "text": r["text"], "calls": r["calls"], "stop": r["stop"]}) + "\n")
                if r["calls"]:
                    outs = []
                    for cid, code in r["calls"]:
                        calls_here += 1
                        tool_calls += 1
                        if calls_here > lim.get("max_tool_calls_per_part", 60):
                            outs.append((cid, "Tool budget for this part is used up. Give your final answer now."))
                        elif code.lstrip().startswith("#CRITIC"):
                            try:
                                out = critic_call(code.lstrip(), vprov, vcfg or {}, mcfg, os.path.join(work, "uploads"), kit)
                            except Exception as e:  # noqa: BLE001
                                out = f"[critic model unavailable: {e!r}]"
                            outs.append((cid, out))
                            tlog.write(json.dumps({"part": i, "critic": out[:1500]}) + "\n")
                        elif code.lstrip().startswith("#LIVE"):
                            out = live.run(code)
                            outs.append((cid, out))
                            tlog.write(json.dumps({"part": i, "live": out[:4000]}) + "\n")
                        elif vprov is not None and code.lstrip().startswith("#SECOND_OPINION"):
                            q = code.split("\n", 1)[1] if "\n" in code else ""
                            try:
                                vr = vprov.call([vprov.user("You are an independent solver. Answer precisely and show the final value.\n\n" + q)])
                                out = f"[second opinion from a DIFFERENT model '{vcfg.get('model')}' - treat as source='model:B']\n" + vr["text"][:4000]
                            except Exception as e:
                                out = f"[second-opinion model unavailable: {e!r}]"
                            outs.append((cid, out))
                            tlog.write(json.dumps({"part": i, "second_opinion": out[:1500]}) + "\n")
                        else:
                            out = sb.run(code)
                            outs.append((cid, out))
                            tlog.write(json.dumps({"part": i, "tool_out": out[:4000]}) + "\n")
                    messages.extend(prov.results(outs))
                    continue
                if r["stop"] == "max_tokens" and conts < 3:
                    conts += 1
                    messages.append(prov.user("Continue."))
                    continue
                break
            if i != 5:
                got = last_json(r["text"])
                for k, v in got.items():
                    if k in ("_conf", "_ledger") and isinstance(v, dict):
                        merged.setdefault(k, {}).update(v)
                    else:
                        merged[k] = v
            log.append({"part": i, "tool_calls": calls_here})
    except Exception as e:  # platform failure: record and let the operator re-run
        log.append({"error": repr(e)})
    finally:
        tlog.close()
        sb.close()
    out_dir = os.path.join(work, "outputs")
    json.dump(merged, open(os.path.join(runs, f"{rid}.json"), "w"), indent=1)
    if os.path.exists(os.path.join(out_dir, "PART5.json")):
        shutil.copy(os.path.join(out_dir, "PART5.json"), os.path.join(runs, f"{rid}_p5.json"))
    for name, dst in (("amp_memory.json", f"{rid}_memory.json"), ("amp_cert.json", f"{rid}_cert.json"),
                      ("amp_evidence.json", f"{rid}_evidence.json")):
        if os.path.exists(os.path.join(out_dir, name)):
            shutil.copy(os.path.join(out_dir, name), os.path.join(runs, dst))
    json.dump(attest_run(_lab(kit), out_dir, given_texts, live), open(os.path.join(runs, f"{rid}_attest.json"), "w"), indent=1)
    price = mcfg.get("price_per_mtok") or {}
    cost = None
    if price:
        cost = sum(usage[k] * float(price.get(k, 0)) for k in usage) / 1e6
    meta = {"run_id": rid, "model_key": row["model"], "model": mcfg.get("model"), "provider": mcfg["provider"],
            "tokens": usage, "cost": cost, "tool_calls": tool_calls, "seconds": round(time.time() - t0, 1),
            "date": time.strftime("%Y-%m-%d %H:%M:%S"), "log": log, "track": "api"}
    json.dump(meta, open(os.path.join(runs, f"{rid}_meta.json"), "w"), indent=1)
    shutil.rmtree(work, ignore_errors=True)
    return meta


def secret_paths(kit, runs):
    """Everything model-written code must not be able to read (the config holds no keys: they come from the env)."""
    paths = [f"/proc/{os.getpid()}/environ"]                   # the runner's environment: the API keys live here
    if os.getpid() != 1 and os.path.exists("/proc/1/environ"):
        paths.append("/proc/1/environ")                      # PID 1 (e.g. the shell that got `docker run -e KEY`)
    for root, _, files in os.walk(kit):
        paths += [os.path.join(root, f) for f in files if f == "KEYS.json"]
    for f in sorted(os.listdir(runs)) if os.path.isdir(runs) else []:
        fp = os.path.join(runs, f)
        if os.path.isfile(fp):
            paths.append(fp)                                 # other runs' answers, memories, transcripts
    return [os.path.abspath(p) for p in paths]


def check_isolation(kit, runs, sandbox_user):
    """Probe, with the sandbox's own credentials, which secret paths model code could read. Returns the readable ones."""
    _private_dirs(runs, sandbox_user)
    canary = os.path.join(runs, ".isolation_canary")
    with open(canary, "w") as f:                             # always present, so the runs/ check never passes vacuously
        f.write("x")
    work = os.path.abspath(os.path.join(runs, "_work", "_probe"))
    shutil.rmtree(work, ignore_errors=True)
    sb = Sandbox(work, timeout=60, user=sandbox_user)
    try:
        return sb.probe(secret_paths(kit, runs))
    finally:
        sb.close()
        shutil.rmtree(work, ignore_errors=True)
        os.remove(canary)


def check_verifiers(cfg, rows):
    """A verifier that is itself one of the compared models leaks one arm into the other (e.g. 55 checking 48)."""
    compared = {r["model"] for r in rows}
    bad = []
    for key in sorted({r["model"] for r in rows if r["model"] in cfg["models"]}):
        v = cfg["models"][key].get("verifier")
        if v and v in compared:
            bad.append(f"model {key!r} has verifier {v!r}, which is a compared model in the plan")
    return bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kit", required=True)
    ap.add_argument("--runs", required=True)
    ap.add_argument("--config", required=True)
    ap.add_argument("--only", default="")
    ap.add_argument("--tier", default="")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--plan", default="")
    ap.add_argument("--sandbox-user", default=os.environ.get("AMP_SANDBOX_USER", ""),
                    help="separate OS user for model-written code (runner must start as root); default $AMP_SANDBOX_USER")
    ap.add_argument("--unsafe-shared-uid", action="store_true",
                    help="allow real API runs even if model code could read secrets (throwaway machine only)")
    ap.add_argument("--allow-compared-verifier", action="store_true",
                    help="allow a verifier that is one of the compared models (breaks the 48 vs 55 comparison)")
    a = ap.parse_args()
    cfg = json.load(open(a.config, encoding="utf-8"))
    if a.sandbox_user:
        os.umask(0o077)                                      # result files private to the runner
    os.makedirs(a.runs, exist_ok=True)
    rows = list(csv.DictReader(open(a.plan or os.path.join(a.kit, "plan.csv"), encoding="utf-8")))
    bad = check_verifiers(cfg, rows)
    if bad and not a.allow_compared_verifier:
        sys.exit("refused: " + "; ".join(bad) + ". Use a verifier outside the compared pair, or none.")
    real = any(m.get("provider") != "mock" for m in cfg["models"].values())
    leaks = check_isolation(a.kit, a.runs, a.sandbox_user or None)
    if leaks:
        msg = "model-written code could read: " + ", ".join(leaks)
        if real and not a.unsafe_shared_uid:
            sys.exit("refused: " + msg + "\nStart the runner as root with --sandbox-user <unprivileged user> (the Docker "
                     "image does), keep kit/sealed out of the sandbox user's reach (chmod -R go-rwx kit/sealed), "
                     "or pass --unsafe-shared-uid on a throwaway machine.")
        print("WARNING (isolation): " + msg, file=sys.stderr)
    only = set(filter(None, a.only.split(",")))
    done = 0
    for row in rows:                                   # plan order = the pre-registered randomised order
        if only and row["run_id"] not in only:
            continue
        if a.tier and not row["tier"].startswith(a.tier):
            continue
        if row["model"] not in cfg["models"]:
            continue
        if os.path.exists(os.path.join(a.runs, f"{row['run_id']}_meta.json")):
            continue                                   # resumable
        meta = run_one(row, a.kit, a.runs, cfg, sandbox_user=a.sandbox_user or None)
        print(f"{row['run_id']} {row['condition']}@{row['model']} seed {row['seed']}: {meta['tool_calls']} tool calls, "
              f"{meta['tokens']['in'] + meta['tokens']['out']} tokens, {meta['seconds']}s" + (f", ERROR {meta['log'][-1]}" if 'error' in meta['log'][-1] else ""))
        done += 1
        if a.limit and done >= a.limit:
            break


if __name__ == "__main__":
    main()
