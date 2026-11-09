# Working instructions: confidence-allocated verification (attach this file together with amp_lab.py)

Load the library once:
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
1. Solve each item once (use the code tool freely) and write your confidence (0 to 1) that it is right.
2. Spend your remaining effort on the items with the LOWEST confidence first: for each, produce another
   attempt and check it with the library's instruments, until two attempts agree; then move to the next
   lowest. Update the confidence after each attempt.
3. Follow the requested output format exactly; the final JSON block is the last thing in your reply.
