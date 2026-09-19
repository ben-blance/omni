"""Tiny example entry point used to demo the OMNI CLI."""

from utils.greetings import greet


def main():
    for name in ("Ada", "Grace", "Alan"):
        print(greet(name))


if __name__ == "__main__":
    main()
