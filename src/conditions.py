"""conditions.py - every experimental condition of the AMP v6 study, in one place.

A condition = which protocol text is attached + whether amp_lab.py is attached + whether memory/feedback files
are carried between chats. Ablations are produced mechanically from ONE source (AMP_v6.src.md) by deleting a
module's tagged blocks, so FULL and every ablation differ in exactly one component and nothing else.
Ablation = the instruction is REMOVED (not forbidden): the model may still do it on its own initiative.
"""
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
MODULES = {
    "EV": "evidence levels + calibrated compute controller",
    "ATT": "attested, independence-aware checks (Registry: derived levels, shared-failure risk, next-check design)",
    "ORACLE": "oracle-first doctrine (external truth: held-out verification, cross-source independence, step chain)",
    "BLIND": "blind independent second method (cross-checks, killer pass)",
    "INS": "insight + rule-induction engines (representation table, experiment, falsify, scale)",
    "IDEA": "idea engine (assumption x operator cells, projections, kill tests, evolution)",
    "DATA": "data-first evidence ledger (external facts before hypotheses; grounding gate on ready())",
    "OUT": "outcomes ledger (reality's verdict on shipped ideas; generators and calibration learn from it)",
    "MEM": "cross-session memory + graded-feedback calibration",
    "LAB": "the tested instrument library amp_lab.py",
}
MODELS = {"48": "Claude Opus 4.8", "55": "Claude Opus 5.5"}

# name: (protocol file or None, attach lab?, carry memory?, description)
CONDITIONS = {
    "FULL": ("AMP_v6.md", True, True, "AMP v6, all components"),
    **{f"no{m}": (f"AMP_v6_no{m}.md", m != "LAB", m != "MEM", f"AMP v6 without {d}") for m, d in MODULES.items()},
    "PLAIN": (None, False, False, "no files: the model as it is (code tool on)"),
    "TOOLS": ("BASE_TOOLS.md", False, False, "baseline: plain tool use (compute + check with code)"),
    "SC5": ("BASE_SC5.md", False, False, "baseline: self-consistency, 5 independent attempts + majority vote"),
    "BON5": ("BASE_BON5.md", True, False, "baseline: best-of-5 selected with the SAME lab instruments as AMP"),
    "CONF": ("BASE_CONF.md", True, False, "closest-prior-art baseline: same lab, extra checks allocated by self-confidence"),
}

TAG = re.compile(r"\[\[(!?)([A-Z]+)\]\](.*?)\[\[/\1\2\]\]", re.S)


def render(src, disabled):
    """Keep [[X]]..[[/X]] when X is enabled, [[!X]]..[[/!X]] when X is disabled; strip the markers."""
    prev = None
    while prev != src:
        prev = src
        src = TAG.sub(lambda m: m.group(3) if (m.group(1) == "!") == (m.group(2) in disabled) else "", src)
    src = re.sub(r"\n{3,}", "\n\n", src)
    return src


def build_protocols(out_dir):
    src = open(os.path.join(HERE, "AMP_v6.src.md"), encoding="utf-8").read()
    os.makedirs(out_dir, exist_ok=True)
    files = {"AMP_v6.md": render(src, set())}
    for m in MODULES:
        txt = render(src, {m})
        files[f"AMP_v6_no{m}.md"] = txt.replace("# AMP v6 —", f"# AMP v6 (variant no{m}) —", 1)
    for name in ("BASE_TOOLS.md", "BASE_SC5.md", "BASE_BON5.md", "BASE_CONF.md"):
        files[name] = open(os.path.join(HERE, "baselines", name), encoding="utf-8").read()
    for name, txt in files.items():
        assert "[[" not in txt, (name, txt[txt.index("[["):][:80])
        open(os.path.join(out_dir, name), "w", encoding="utf-8").write(txt)
    return files


def opening_message(cond):
    proto, lab, mem, _ = CONDITIONS[cond]
    if proto is None:
        return "Solve the attached task. Use the code tool if it helps."
    att = "Follow the attached protocol file in every reply of this conversation" + (", starting with its Boot step" if lab or proto.startswith("AMP") else "")
    return att + ". Then solve the attached task."
