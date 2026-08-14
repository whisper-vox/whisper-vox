#!/usr/bin/env python3
"""Whisper Vox - guard the platform contract.

platforms/__init__ stacks base's defaults first and lets the OS backend override
what it implements. That only works if every name a backend exports also exists
in base: on the OTHER platform there is no backend to provide it, and the call
would fail with AttributeError at the worst moment. A name defined in base but
missing from its __all__ is the same trap, since the stacking is star-imports.

This is quick to get wrong while adding a function and impossible to notice on
the platform you happen to be working on. Run it after touching platforms/.
"""
import ast
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent.parent / 'src' / 'platforms'


def names(path):
    tree = ast.parse(path.read_text())
    defined = {n.name for n in tree.body
               if isinstance(n, ast.FunctionDef) and not n.name.startswith('_')}
    exported = set()
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
                getattr(t, 'id', None) == '__all__' for t in node.targets):
            exported = {e.value for e in node.value.elts}
    return defined, exported


def main():
    base_defined, base_exported = names(HERE / 'base.py')
    problems = []

    hidden = sorted(base_defined - base_exported)
    if hidden:
        problems.append(f'base.py defines but does not export: {", ".join(hidden)}')
    missing = sorted(base_exported - base_defined)
    if missing:
        problems.append(f'base.py exports but does not define: {", ".join(missing)}')

    for backend in ('win.py', 'mac.py'):
        defined, exported = names(HERE / backend)
        undefined = sorted(exported - defined)
        if undefined:
            problems.append(f'{backend} exports but does not define: {", ".join(undefined)}')
        orphans = sorted(exported - base_exported)
        if orphans:
            problems.append(
                f'{backend} exports names base.py has no default for: '
                f'{", ".join(orphans)} - the other platform would crash on them')

    if problems:
        print('Platform contract problems:')
        for p in problems:
            print(f'  - {p}')
        return 1
    print('Platform contract OK: every backend name has a default in base.py.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
