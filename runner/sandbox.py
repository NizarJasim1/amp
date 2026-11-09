"""sandbox.py - a persistent Python session for one run (like the app's code tool: variables survive between calls).

The child process keeps one globals dict, executes each code block, returns stdout+stderr (truncated), and is
restarted on timeout. It runs inside a per-run work folder:
    work/uploads   attached files (paths inside them rewritten, see PATH_MAP)
    work/outputs   files the model saves; the child's working directory
Code written for the app (/mnt/user-data/uploads, /mnt/user-data/outputs) is rewritten to these folders.

SECURITY: this executes model-written code on the machine that runs it. Run the runner inside a throwaway VM or
the provided Docker image, never on a machine with secrets.

v6.7 isolation. Removing secret-named variables from the child's environment is NOT enough: a child that runs as
the same OS user can read /proc/<runner pid>/environ (where the API key sits) and every file the runner can read
(kit/sealed/KEYS.json, other runs' answers). So:
  - the child gets a MINIMAL environment built from scratch (PATH, HOME, locale + the public extra_env), nothing
    inherited from the runner;
  - with `user=` (runner started as root, e.g. in the Docker image) the child runs as that separate, unprivileged
    OS user: it cannot read the runner's /proc entries or root-only files, and the work folder is handed to it;
  - `probe(paths)` runs a one-shot child with the same credentials and reports which of the given paths it can
    read; amp_runner.py refuses real API runs when anything secret is readable (see check_isolation there).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading

CHILD = r'''
import io, json, sys, traceback, contextlib
G = {"__name__": "__main__"}
for line in sys.stdin:
    req = json.loads(line)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        try:
            try:
                code, mode = compile(req["code"], "<cell>", "eval"), "eval"
            except SyntaxError:
                code, mode = compile(req["code"], "<cell>", "exec"), "exec"
            if mode == "eval":
                val = eval(code, G)
                if val is not None:
                    print(repr(val))
            else:
                exec(code, G)
        except SystemExit:
            print("SystemExit ignored")
        except BaseException:
            traceback.print_exc()
    sys.__stdout__.write(json.dumps({"out": buf.getvalue()}) + "\n")
    sys.__stdout__.flush()
'''


def path_map(work):
    return {"/mnt/user-data/uploads": os.path.join(work, "uploads"), "/mnt/user-data/outputs": os.path.join(work, "outputs")}


def rewrite(text, work):
    for a, b in path_map(work).items():
        text = text.replace(a, b)
    return text


PROBE = r'''
import json, sys
hits = []
for p in json.loads(sys.stdin.read()):
    try:
        with open(p, "rb") as f:
            f.read(1)
        hits.append(p)
    except Exception:
        pass
print(json.dumps(hits))
'''


def resolve_user(user):
    """'name' or 'uid' -> (uid, gid); None / '' -> None (same user as the runner)."""
    if user in (None, ""):
        return None
    import pwd
    pw = pwd.getpwuid(int(user)) if str(user).isdigit() else pwd.getpwnam(str(user))
    return pw.pw_uid, pw.pw_gid


class Sandbox:
    def __init__(self, work, timeout=300, max_out=12000, env=None, user=None):
        work = os.path.abspath(work)
        self.work, self.timeout, self.max_out, self.extra_env = work, timeout, max_out, dict(env or {})
        self.ids = resolve_user(user)
        if self.ids and os.geteuid() != 0:
            raise PermissionError("Sandbox(user=...) needs the runner to start as root (the Docker image does this)")
        os.makedirs(os.path.join(work, "uploads"), exist_ok=True)
        os.makedirs(os.path.join(work, "outputs"), exist_ok=True)
        if self.ids:
            d = os.path.dirname(work)
            while d and d != os.path.dirname(d):
                if not os.stat(d).st_mode & 0o001:
                    raise PermissionError(f"the sandbox user cannot reach its work folder: {d} is not traversable "
                                          "(chmod o+x, or 0o711 to keep it unlistable)")
                d = os.path.dirname(d)
        self.p = None
        self._start()

    def _env(self):
        """Built from scratch: nothing of the runner's environment (API keys, tokens, anything) is inherited."""
        env = {"PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"), "HOME": os.path.join(self.work, "outputs"),
               "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8"}
        env.update(self.extra_env)                           # e.g. AMP_TRACK / AMP_GIVEN_SHA256 (public facts, no secrets)
        return env

    def _cred(self):
        if not self.ids:
            return {}
        return {"user": self.ids[0], "group": self.ids[1], "extra_groups": []}

    def _hand_over(self):
        """Give the work folder (and every file the runner has put there since) to the sandbox user, private to it."""
        if not self.ids:
            return
        uid, gid = self.ids
        for root, dirs, files in os.walk(self.work):
            os.chown(root, uid, gid)
            os.chmod(root, 0o700)
            for f in files:
                fp = os.path.join(root, f)
                if not os.path.islink(fp):
                    os.chown(fp, uid, gid)
                    os.chmod(fp, 0o600)

    def _start(self):
        self._hand_over()
        self.p = subprocess.Popen([sys.executable, "-u", "-c", CHILD], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.DEVNULL, text=True, cwd=os.path.join(self.work, "outputs"),
                                  env=self._env(), **self._cred())

    def probe(self, paths):
        """Which of `paths` can code in this sandbox read? (one-shot child, same user and environment)"""
        self._hand_over()
        r = subprocess.run([sys.executable, "-c", PROBE], input=json.dumps(list(paths)), capture_output=True, text=True,
                           cwd=os.path.join(self.work, "outputs"), env=self._env(), timeout=60, **self._cred())
        try:
            return json.loads(r.stdout.strip().splitlines()[-1])
        except Exception:  # noqa: BLE001  a probe that cannot report is treated as a leak of everything
            return list(paths)

    def run(self, code):
        code = rewrite(code, self.work)
        self._hand_over()                                    # files the runner added since the last call
        result = {}

        def talk():
            try:
                self.p.stdin.write(json.dumps({"code": code}) + "\n")
                self.p.stdin.flush()
                result["line"] = self.p.stdout.readline()
            except Exception as e:  # broken pipe etc.
                result["err"] = repr(e)
        t = threading.Thread(target=talk, daemon=True)
        t.start()
        t.join(self.timeout)
        if t.is_alive() or "line" not in result or not result["line"]:
            self.close()
            self._start()
            return f"[timeout or crash after {self.timeout}s: the Python session was restarted and its variables were lost]"
        out = json.loads(result["line"])["out"]
        if len(out) > self.max_out:
            out = out[: self.max_out // 2] + f"\n...[{len(out) - self.max_out} characters cut]...\n" + out[-self.max_out // 2:]
        return out or "(no output)"

    def close(self):
        if self.p and self.p.poll() is None:
            self.p.kill()
