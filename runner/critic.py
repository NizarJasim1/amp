"""critic.py - send a sealed idea/plan packet to an INDEPENDENT critic model, outside any run.

    python runner/critic.py --packet packet.json --config providers.json --critic 55 --author 48 --out reply.txt

packet.json is written by pool.packet(brief, author=..., path="packet.json"). The critic gets a brand-new
conversation containing ONLY the sealed prompt. It refuses when critic and author are the same model.
Then, in the lab:  pool.ingest(open("reply.txt").read(), source="model:<critic model>")
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import amp_runner as R  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--packet", required=True)
    ap.add_argument("--config", required=True)
    ap.add_argument("--critic", required=True, help="model key in the config that plays the critic")
    ap.add_argument("--author", default="", help="model key that wrote the ideas (must differ)")
    ap.add_argument("--out", default="")
    a = ap.parse_args(argv)
    cfg = json.load(open(a.config, encoding="utf-8"))["models"]
    ccfg, acfg = cfg[a.critic], cfg.get(a.author, {})
    if a.author and (a.author == a.critic or (ccfg.get("model") and ccfg.get("model") == acfg.get("model"))):
        sys.exit("refused: critic and author are the same model")
    pkt = json.load(open(a.packet, encoding="utf-8"))
    out_dir = os.path.dirname(os.path.abspath(a.out)) if a.out else os.getcwd()
    text = R.critic_call("#CRITIC\n" + json.dumps(pkt), R.PROVIDERS[ccfg["provider"]](ccfg), ccfg, acfg, out_dir)
    saved = os.path.join(out_dir, f"critic_{pkt['packet']}.txt")
    if a.out and os.path.exists(saved):
        os.replace(saved, a.out)
    print(text)


if __name__ == "__main__":
    main()
