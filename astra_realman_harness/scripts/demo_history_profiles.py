#!/usr/bin/env python3
"""Create clearly labelled synthetic fixed-observation inputs for all four profiles."""
import argparse
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from fixtures.synthetic_history import make_run
from prepare_history_replay import prepare

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',required=True,type=Path,help='New directory under harness/logs')
    a=p.parse_args()
    source=make_run(a.output)
    print(prepare(source,7,source/'four-profiles'))

if __name__=='__main__':main()
