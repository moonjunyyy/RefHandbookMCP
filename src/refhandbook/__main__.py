"""python -m refhandbook: the CLI (the console script is `refhandbook`)."""
import sys

from .cli import main

sys.exit(main())
