"""Run with python -m evaluation --help from the repository root."""
import argparse
import json
from pathlib import Path

from .adapters import RecordedEngine, RecordedText
from .blind import blind
from .data import validate
from .metrics import score
from .runner import run


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Keep private artifacts private and refuse accidental overwrite.
    with path.open('x', encoding='utf-8') as stream:
        path.chmod(0o600)
        json.dump(data, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')


def main():
    parser = argparse.ArgumentParser(description='Offline pilot harness; no network calls')
    commands = parser.add_subparsers(dest='command', required=True)
    p = commands.add_parser('validate')
    p.add_argument('manifest')
    p = commands.add_parser('run')
    for name in ('manifest', 'config', 'tape', 'engine', 'output'):
        p.add_argument(name)
    p = commands.add_parser('blind')
    for name in ('manifest', 'result', 'public_dir', 'private_dir'):
        p.add_argument(name)
    p.add_argument('--seed', type=int, required=True)
    p = commands.add_parser('score')
    for name in ('result', 'key', 'ratings', 'output'):
        p.add_argument(name)
    p.add_argument('--asr')
    args = parser.parse_args()
    if args.command == 'validate':
        data = validate(read(args.manifest))
        print(f"VALID: {len(data['cases'])} cases; synthetic={data['synthetic']}")
    elif args.command == 'run':
        result = run(read(args.manifest), read(args.config), RecordedText(read(args.tape)),
                     RecordedEngine(read(args.engine)))
        write(args.output, result)
        print(result['status'])
        return 0 if result['status'] == 'complete' else 2
    elif args.command == 'blind':
        public, private = Path(args.public_dir).resolve(), Path(args.private_dir).resolve()
        if public == private or public in private.parents or private in public.parents:
            parser.error('public and private directories must be separate and non-nested')
        packet, key, ratings = blind(read(args.result), validate(read(args.manifest)), args.seed)
        write(public / 'answers.json', packet)
        write(public / 'ratings.json', ratings)
        write(private / 'key.json', key)
    else:
        write(args.output, score(read(args.result), read(args.key), read(args.ratings),
                                 read(args.asr) if args.asr else []))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
