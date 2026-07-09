"""Allow `python -m parser_universal.cli` to dispatch to cli()."""

from parser_universal.cli.main import cli

if __name__ == "__main__":
    cli()
