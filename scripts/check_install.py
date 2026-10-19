"""Check that the active interpreter uses this checkout's modified Harbor."""

from importlib.metadata import version
from pathlib import Path


def main():
    import harbor
    from harbor.utils.redaction import scrub_directory

    repo = Path(__file__).resolve().parents[1]
    expected = (repo / "vendor/harbor/src/harbor").resolve()
    actual = Path(harbor.__file__).resolve().parent
    if actual != expected or version("harbor") != "0.21.0+residual.1":
        raise SystemExit("Harbor source mismatch; run bash scripts/install.sh")
    if not callable(scrub_directory):
        raise SystemExit("Harbor artifact protection is missing")
    print("Harbor 0.21.0+residual.1: local source verified")


if __name__ == "__main__":
    main()
