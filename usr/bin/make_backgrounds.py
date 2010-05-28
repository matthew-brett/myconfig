#!/usr/bin/env python
from __future__ import with_statement

import os
from os.path import join as pjoin
import mimetypes

import argparse

out_target = pjoin(os.environ['HOME'], '.gnome2', 'backgrounds.xml')
options = 'spanner' 

xml_template = \
'''<wallpaper deleted="false">
   <name>NAME</name>
   <filename>FILE</filename>
   <options>%s</options>
   <shade_type>solid</shade_type>
   <pcolor>#68684b4b3333</pcolor>
   <scolor>#68684b4b3333</scolor>
</wallpaper>''' % options

xml_header = \
'''<?xml version="1.0"?>
<!DOCTYPE wallpapers SYSTEM "gnome-wp-list.dtd">
<wallpapers> '''

xml_footer = \
'''</wallpapers>'''


def papers_to_stream(filenames, fileobj):
    fileobj.write(xml_header + '\n')
    used_filenames = []
    for filepath in filenames:
        filepath = os.path.abspath(filepath)
        pth, fname = os.path.split(filepath)
        mimetype = mimetypes.guess_type(fname)[0]
        if not mimetype or mimetype.split ('/')[0] != "image":
            continue
        out = xml_template.replace('NAME', fname)
        out = out.replace('FILE', filepath)
        fileobj.write(out + '\n')
        used_filenames.append(filepath)
    fileobj.write(xml_footer + '\n')
    return used_filenames


def main():
    # create the parser
    parser = argparse.ArgumentParser()
    # add the arguments
    parser.add_argument('files', nargs='+')
    parser.add_argument('-o', '--output-file', default=out_target)
    parser.add_argument('-v', '--verbose', action='store_true')
    # parse the command line
    args = parser.parse_args()
    with open(args.output_file, 'wt') as fileobj:
        used_files = papers_to_stream(args.files, fileobj)
    if args.verbose:
        print 'Used files:\n', '\n'.join(used_files)
        print 'XML output to %s' % args.output_file


if __name__ == '__main__':
    main()
