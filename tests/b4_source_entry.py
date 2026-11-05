"""Explicit source-mode entry for Linux smoke; no installed-package claim."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
target=sys.argv.pop(1)
if target=='journal':
    from agent.journal_cli import main
elif target=='compare':
    from workloads.__main__ import main
else:
    raise SystemExit(2)
raise SystemExit(main())
