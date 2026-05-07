"""Entry point for `python -m pytxt` and the `pytxt` console script."""
import asyncio

from pytxt.composition import main


def run() -> None:
    """Synchronous wrapper used by the console script in pyproject.toml."""
    asyncio.run(main())


if __name__ == "__main__":
    run()
