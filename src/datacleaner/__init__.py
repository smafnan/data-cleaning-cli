"""datacleaner - a defensive, configurable CSV cleaning toolkit.

The package exposes a small, well-typed API so the cleaning logic can be used
either from the command line (see :mod:`datacleaner.cli`) or imported directly
into notebooks and other Python code.

Public surface:
    - :class:`~datacleaner.cleaner.CleaningConfig`  -> how to clean
    - :class:`~datacleaner.cleaner.CleaningReport`   -> what happened
    - :func:`~datacleaner.cleaner.clean_dataframe`   -> the core transform
"""

from .cleaner import (
    CleaningConfig,
    CleaningReport,
    clean_dataframe,
)

__all__ = ["CleaningConfig", "CleaningReport", "clean_dataframe"]
__version__ = "1.0.0"
