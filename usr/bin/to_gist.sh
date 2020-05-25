#!/bin/bash
if [ -z "$1" ]; then
    echo "Filename for gist"
    exit 1
fi
# https://stackoverflow.com/questions/2664740/extract-file-basename-without-path-and-extension-in-bash#2664746
in_path=$1
out_path=${in_path##*/}
out_path=${out_path%.*}
url=$(gist $in_path)
echo "Gist is $url; writing to $out_path."
git clone $url $out_path
