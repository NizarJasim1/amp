# Working instructions: best-of-5 with verification (attach this file together with amp_lab.py)

Load the verification library once:
```python
import glob, importlib.util, sys
path = next(p for pat in ('/mnt/user-data/uploads/*amp_lab*.py', '/mnt/**/*amp_lab*.py', '**/*amp_lab*.py')
            for p in glob.glob(pat, recursive=True))
spec = importlib.util.spec_from_file_location('amp_lab', path); lab = importlib.util.module_from_spec(spec)
sys.modules['amp_lab'] = lab; spec.loader.exec_module(lab)
from amp_lab import *
lab_help()
```
For every task in this conversation:
1. Produce FIVE candidate solutions per item (use the code tool freely).
2. Verify every candidate with the library's instruments (brute force on small cases, `crosscheck`, exact
   validators for constructions) and keep the candidate that passes the most checks; for scored items, the
   best valid score.
3. Follow the requested output format exactly; the final JSON block is the last thing in your reply.
