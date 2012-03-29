#!/usr/bin/env python
DESCRIP = """ Simple desktop wallpaper switcher """
EPILOG = \
""" Switch wallpapers at interval, selecting from files passed on command line

e.g. xfce_randback.py /path/to/file.jpg /path/to/file2.jpg --interval=30
"""

import random
from subprocess import check_call
from time import sleep
from argparse import ArgumentParser, RawDescriptionHelpFormatter

def main():
    # create the parser
    parser = ArgumentParser(description=DESCRIP,
                            epilog=EPILOG,
                            formatter_class=RawDescriptionHelpFormatter)
    # add the arguments
    parser.add_argument('files', nargs='+')
    parser.add_argument('-i', '--interval', default=60,
                        help='Refresh interval in minutes')
    args = parser.parse_args()
    files = args.files
    time = float(args.interval) * 60
    print("Starting random wallpaper switcher; ctrl-C to stop")
    while True:
        wall = random.choice(files)
        print("Changing to %s" % wall)
        check_call('xfconf-query -c xfce4-desktop '
                   '-p /backdrop/screen0/monitor0/image-path '
                   '-s %s' % wall, shell=True)
        sleep(time)


if __name__ == '__main__':
    main()
