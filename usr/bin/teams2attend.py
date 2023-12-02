#!/usr/bin/env python3
""" Write out Teams attendance in suitable order
"""

import re
from pathlib import Path
from argparse import ArgumentParser, RawDescriptionHelpFormatter

import pandas as pd


START_TIME_RE = re.compile(
    r'^Start time\s+(.*)?$',
    flags=re.M)

PARTICIPANT_RE = re.compile(r'^\d.\s+Participants$')

INSTRUCTORS = (
    'Matthew Brett',
    'Peter Rush',
    'Anson Cheung')


def write_participants(fname):
    csv_path = Path(fname)
    contents = csv_path.read_text(encoding='utf_16_le')
    start_match = START_TIME_RE.search(contents)
    ts_str = (str(pd.to_datetime(start_match.groups()[0]))
            .replace(' ', '_')
            .replace(':', '_'))
    out_path = Path(csv_path.parent / f'attend-{ts_str}.csv')

    lines = contents.splitlines()
    for i, line in enumerate(lines):
        if PARTICIPANT_RE.match(line):
            break
    else:
        raise RuntimeError('No participant line')

    participants = []
    for line in lines[i + 2:]:
        L = line.strip()
        if not L:
            break
        participant = L.split('\t')[0]
        if not participant in INSTRUCTORS:
            participants.append(participant)

    participants.sort()
    out_path.write_text('Name\n' + '\n'.join(participants))


def get_parser():
    parser = ArgumentParser(description=__doc__,  # Usage from docstring
                            formatter_class=RawDescriptionHelpFormatter)
    parser.add_argument('meeting_fnames', nargs='+',
                        help='Filenames for meetings')
    return parser


def main():
    parser = get_parser()
    args = parser.parse_args()
    for fname in args.meeting_fnames:
        write_participants(fname)


if __name__ == '__main__':
    main()
