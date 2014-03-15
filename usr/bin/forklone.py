#!/usr/bin/env python
DESCRIP = "Clone github fork, add upstream remote and main-master branch"
EPILOG = \
"""Clone github fork of some repo, add remote pointing to upstream, add
main-master branch. Typical use for cloning a repo to which you do not have
write permission to upstream::

    forklone.py ipython ipython

or for when you do have write permission::

    forklone.py nibabel nipy --upstream-w

"""

import os
from argparse import ArgumentParser, RawDescriptionHelpFormatter
from subprocess import check_call, Popen, PIPE

def bt(cmd):
    proc = Popen(cmd, stdout=PIPE, stderr=PIPE, shell=True)
    out, err = proc.communicate()
    return out.strip()


def gh_url(user, reponame, mode='git'):
    if mode == 'git':
        fmt = 'git://github.com/{user}/{reponame}.git'
    elif mode == 'https-rw':
        fmt = 'https://{user}@github.com/{user}/{reponame}.git'
    elif mode == 'https-ro':
        fmt = 'https://github.com/{user}/{reponame}.git'
    elif mode == 'ssh':
        fmt = 'git@github.com:{user}/{reponame}.git'
    else:
        raise ValueError('Did not expect {0} as mode'.format(mode))
    return fmt.format(user=user, reponame=reponame)


def get_gh_user():
    cmd = 'git config github.user'
    return bt(cmd)


def main():
    parser = ArgumentParser(description=DESCRIP,
                            epilog=EPILOG,
                            formatter_class=RawDescriptionHelpFormatter)
    parser.add_argument('reponame', type=str,
                        help='name of repository')
    parser.add_argument('upstream_user', type=str,
                        help='name of github upstream user')
    parser.add_argument('--my-user', type=str,
                        help='personal github user name')
    parser.add_argument('--upstream-w', action='store_true',
                        help='whether upstream should be rw')
    parser.add_argument('--https', type=str, default = '',
                        help="can be one of 'r', 'w', 'rw' to choose https as "
                             "transport protocol for git")
    args = parser.parse_args()
    reponame = args.reponame
    my_user = args.my_user
    if my_user is None:
        my_user = get_gh_user()
        if my_user == '':
            raise RuntimeError("You didn't specify --my-user and I couldn't "
                               "get your github user from "
                               "``git config github.user``;\n"
                               "Consider setting your github username with "
                               "``git config --global github.user username``")
    up_user = args.upstream_user
    w_proto = 'https-rw' if 'w' in args.https else 'ssh'
    r_proto = 'https-ro' if 'r' in args.https else 'git'
    fork_repo = gh_url(my_user, reponame, mode=w_proto)
    up_remote = 'origin'
    upstream_proto = w_proto if args.upstream_w else r_proto
    up_repo = gh_url(up_user, reponame, mode=upstream_proto)
    check_call('git clone --origin={0} {1}'.format(my_user, fork_repo), shell=True)
    os.chdir(reponame)
    check_call('git remote add {0} {1} --fetch'.format(up_remote, up_repo),
               shell=True)
    check_call('git checkout -b main-master -t {0}/master'.format(up_remote),
               shell=True)


if __name__ == '__main__':
    main()
