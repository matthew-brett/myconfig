#!/usr/bin/env python
DESCRIP = "Clone github fork, add upstream remote and main-master branch"
EPILOG = \
"""Clone github fork of some repo, add remote pointing to upstream, add
main-master branch """

import os
from argparse import ArgumentParser, RawDescriptionHelpFormatter
from subprocess import check_call


def gh_url(user, reponame, mode='git'):
    if mode == 'git':
        fmt = 'git://github.com/{user}/{reponame}.git'
    if mode == 'https':
        fmt = 'https://{user}@github.com/{user}/{reponame}.git'
    elif mode == 'ssh':
        fmt = 'git@github.com:{user}/{reponame}.git'
    return fmt.format(user=user, reponame=reponame)


def main():
    parser = ArgumentParser(description=DESCRIP,
                            epilog=EPILOG,
                            formatter_class=RawDescriptionHelpFormatter)
    parser.add_argument('reponame', type=str,
                        help='name of repository')
    parser.add_argument('upstream_user', type=str,
                        help='name of github upstream user')
    parser.add_argument('--my-user', type=str, default='matthew-brett',
                        help='personal github user name')
    parser.add_argument('--upstream-w', action='store_true',
                        help='whether upstream should be rw')
    args = parser.parse_args()
    reponame = args.reponame
    my_user = args.my_user
    up_user = args.upstream_user
    fork_repo = gh_url(my_user, reponame, mode='ssh')
    if args.upstream_w:
        up_remote = 'upstream-rw'
        up_repo = gh_url(up_user, reponame, mode='ssh')
    else:
        up_remote = 'upstream-ro'
        up_repo = gh_url(up_user, reponame, mode='git')
    check_call('git clone {0}'.format(fork_repo), shell=True)
    os.chdir(reponame)
    check_call('git remote add {0} {1} --fetch'.format(up_remote, up_repo),
               shell=True)
    check_call('git checkout -b main-master -t {0}/master'.format(up_remote),
               shell=True)


if __name__ == '__main__':
    main()
