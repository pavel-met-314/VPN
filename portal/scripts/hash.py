#!/usr/bin/env python3
from __future__ import annotations

import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.auth import hash_password  # noqa: E402


def main() -> int:
    if len(sys.argv) > 1:
        password = sys.argv[1]
    else:
        password = getpass.getpass("Пароль: ")
        confirm = getpass.getpass("Повтор: ")
        if password != confirm:
            print("Пароли не совпали", file=sys.stderr)
            return 1

    if len(password) < 8:
        print("Минимум 8 символов", file=sys.stderr)
        return 1

    print(hash_password(password))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
