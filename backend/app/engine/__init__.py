"""Media engine adapted from MoneyPrinterV2.

Heavy dependencies (MoviePy, ImageMagick) are imported lazily inside functions
so the rest of the backend imports and runs without them installed.
"""
