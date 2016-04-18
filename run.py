#!/usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import print_function, unicode_literals

import argparse
import logging
import os
import re
import subprocess
import sys
import tempfile
import time

NAME = "ci-dnf-stack"
LOGGER = logging.getLogger(NAME)
ROOT = os.path.dirname(os.path.abspath(__file__))

def _build_in_copr(srpm, p_owner, p_name, chroot=None):
    """
    :param srpm: src.rpm to build
    :type srpm: str
    :param p_owner: COPR project owner
    :type p_owner: str
    :param p_name: COPR project name
    :type p_name: str
    :param chroot: Chroot to use
    :type chroot: str | None
    :return: URLs to RPMs
    :rtype: list
    """
    import bs4
    import copr
    import requests
    client = copr.client_v2.client.CoprClient.create_from_file_config()
    projects = client.projects.get_list(owner=p_owner, name=p_name, limit=1)
    if not projects:
        raise Exception("Project not found")
    project = projects.projects[0]
    if not chroot:
        chroots = [x.name for x in project.get_project_chroot_list()]
    else:
        chroots = [project.get_project_chroot(chroot)]
    build = project.create_build_from_file(srpm, chroots=chroots, enable_net=False)
    while True:
        build = build.get_self()
        if build.state in ["skipped", "failed", "succeeded"]:
            break
        time.sleep(5)
    success, rpms = True, []
    for task in build.get_build_tasks():
        task = task.get_self()
        if task.state == "failed":
            success = False
        else:
            url_prefix = task.result_dir_url
            resp = requests.get(url_prefix)
            if resp.status_code != 200:
                raise Exception("Failed to fetch")
            soup = bs4.BeautifulSoup(resp.text)
            for link in soup.find_all("a", href=True):
                if link["href"].endswith(".rpm") and not link["href"].endswith(".src.rpm"):
                    rpms.append("{}/{}".format(url_prefix, link["href"]))

    if not success:
        raise Exception("Build failed")

    return rpms

def _run_tests(log_dir, dnf_cmd="dnf"):
    """Run functional tests
    :param log_dir: Log directory
    :type log_dir: str
    :param dnf_cmd: DNF command
    :type dnf_cmd: str
    """
    subprocess.call(["behave", os.path.join(ROOT, "dnf-docker-test", "features"),
                     "-D", "dnf_command_version={}".format(dnf_cmd),
                     "--junit", "--junit-directory", log_dir])

def main():
    parser = argparse.ArgumentParser(description="Test the DNF stack.")
    subparsers = parser.add_subparsers(help="Action to do", dest="action")

    srpm_parser = subparsers.add_parser("build-srpm", help="Build src.rpm")
    srpm_parser.add_argument("upstream", help="Path to upstream git repo")
    srpm_parser.add_argument("spec", help="Path to spec file")

    rpm_parser = subparsers.add_parser("build-rpm", help="Build rpm from src.rpm")
    rpm_type_parser = rpm_parser.add_subparsers(help="What to use to build rpm", dest="builder")
    rpm_parser.add_argument("srpm", help="Path to src.rpm")
    rpm_type_parser.add_parser("rpmbuild", help="Build rpm using rpmbuild")
    rpm_type_parser.add_parser("mock", help="Build rpm using mock")
    coprbuild_parser = rpm_type_parser.add_parser("copr", help="Build rpm using COPR")
    coprbuild_parser.add_argument("project_owner", help="COPR project owner")
    coprbuild_parser.add_argument("project_name", help="COPR project name")
    coprbuild_parser.add_argument("-c", "--chroot", help="COPR chroot name")

    test_parser = subparsers.add_parser("run-tests", help="Run functional tests")
    test_type_parser = test_parser.add_subparsers(help="Where to run tests", dest="test_type")
    test_parser.add_argument("dnf_cmd", help="DNF command to use")
    test_parser.add_argument("rpms", help="RPM(s) to install", nargs="*", metavar="RPM")
    test_type_parser.add_parser("local", help="Run tests locally")
    docker_parser = test_type_parser.add_parser("docker", help="Run tests in docker")
    docker_parser.add_argument("image", help="Base image")

    args = parser.parse_args()

    logfn = os.path.join(ROOT, "{}.log".format(NAME))
    logfmt = "%(asctime)s.%(msecs)03d:%(levelname)s:%(message)s"
    logging.basicConfig(filename=logfn,
                        format=logfmt,
                        level=logging.DEBUG)
    handler = logging.StreamHandler()
    handler.setLevel(logging.INFO)
    handler.setFormatter(logging.Formatter(logfmt))
    LOGGER.addHandler(handler)

    if args.action == "build-srpm":
        from ci_dnf_stack import utils
        print(utils.build_srpm(ROOT, args.upstream, args.spec))
    elif args.action == "build-rpm":
        if args.builder == "rpmbuild":
            out_dir = tempfile.mkdtemp(prefix="rpm", dir=ROOT)
            out = subprocess.check_output(["rpmbuild", "--rebuild", args.srpm,
                                           "--define", "_rpmdir {}".format(out_dir)])
            rpms = []
            _wrt = False
            regex = re.compile(r"^Wrote: (.+\.rpm)$")
            for line in reversed(out.decode("utf-8").split("\n")):
                match = regex.match(line)
                if match:
                    _wrt = True
                    rpms.append(match.group(1))
                elif _wrt:
                    break
        elif args.builder == "mock":
            raise NotImplementedError
        elif args.builder == "copr":
            rpms = _build_in_copr(args.srpm, args.project_owner, args.project_name, args.chroot)
        print(" ".join(rpms))
    elif args.action == "run-tests":
        log_dir = tempfile.mkdtemp(prefix="test-results", dir=ROOT)
        if args.test_type == "local":
            _run_tests(log_dir, args.dnf_cmd)
        elif args.test_type == "docker":
            raise NotImplementedError
        print(log_dir)

if __name__ == "__main__":
    main()
