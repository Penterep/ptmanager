#!/usr/bin/python3
"""
    Copyright (c) 2024 Penterep Security s.r.o.

    ptmanager is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    ptmanager is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with ptmanager.  If not, see <https://www.gnu.org/licenses/>.
"""

import argparse
import os
import sys; sys.path.extend([__file__.rsplit("/", 1)[0], os.path.join(__file__.rsplit("/", 1)[0], "modules")])
import threading

from _version import __version__
from modules.config import Config
from modules.project_manager import ProjectManager
from modules.tools_manager import ToolsManager

import requests
from ptlibs import ptprinthelper, ptjsonlib


class PtManager:
    def __init__(self, args) -> None:
        self.ptjsonlib: object    = ptjsonlib.PtJsonLib()
        self.config: object       = Config(config_path=os.path.join(os.path.expanduser("~"), ".ptmanager/"))
        self.proxies: dict        = args.proxy
        self.no_ssl_verify: bool  = args.no_ssl_verify
        self.use_json: bool       = False
        self.debug: bool          = args.debug

    def run(self, args: argparse.Namespace) -> None:
        """Main method"""

        if args.init or not self.config.get_satid():
            self._get_project_manager().register_uid()

        elif args.project_new:
            self._get_project_manager().register_project(args.target, args.auth)

        elif args.project_start:
            self._get_project_manager().start_project(self.validate_project_id(args.project_start))

        elif args.project_end:
            self._get_project_manager().end_project(self.validate_project_id(args.project_end))

        elif args.project_reset:
            self._get_project_manager().reset_project(self.validate_project_id(args.project_reset))

        elif args.project_delete:
            self._get_project_manager().delete_project(self.validate_project_id(args.project_delete))

        elif args.project_list:
            self._get_project_manager().list_projects()

        elif args.tools_list:
            self._get_tools_manager().print_available_tools()

        elif args.tools_install:
            self._get_tools_manager().prepare_install_update_delete_tools(args.tools_install, do_install=True)

        elif args.tools_update:
            self._get_tools_manager().prepare_install_update_delete_tools(args.tools_update, do_update=True)

        elif args.tools_delete:
            self._get_tools_manager().prepare_install_update_delete_tools(args.tools_delete, do_delete=True)

        else:
            self.ptjsonlib.end_error("Bad argument combination", self.use_json)

        self.config.save()

    def _get_project_manager(self) -> ProjectManager:
        return ProjectManager(ptjsonlib=self.ptjsonlib, use_json=self.use_json, proxies=self.proxies, no_ssl_verify=self.no_ssl_verify, config=self.config, debug=self.debug)

    def _get_tools_manager(self) -> ToolsManager:
        return ToolsManager(ptjsonlib=self.ptjsonlib, use_json=self.use_json)

    def validate_project_id(self, project_id) -> int:
        projects_list = [str(i) for i in range(1, len(self.config.get_projects())+1)]
        if not project_id.isdigit():
            self.ptjsonlib.end_error(f"Entered Project ID is not a number", self.use_json)
        if project_id not in projects_list:
            self.ptjsonlib.end_error(f"Project ID '{project_id}' does not exist", self.use_json)
        return int(project_id) - 1


def get_help() -> list[dict[str,any]]:
    return [
        {"description": ["Penterep Script Management Tool"]},
        {"usage": ["ptmanager <options>"]},
        {"usage_example": [
            "ptmanager --init",
            "ptmanager --project-new --target <target> --auth <auth>",
            "ptmanager --project-start 1",
            "ptmanager --tools-install ptaxfr ptwebdiscover",
        ]},
        {"Manager options": [
            ["-pn",  "--project-new",          "",         "Register new project"],
            ["-pl",  "--project-list",         "",         "List available projects"],
            ["-ps",  "--project-start",        "<id>",     "Start project"],
            ["-pr",  "--project-reset",        "<id>",     "Restart project"],
            ["-pd",  "--project-delete",       "<id>",     "Delete project"],
            ["-pe",  "--project-end",          "<id>",     "End project"],
            ]
        },
        {"Tools options": [
            ["-tl",  "--tools-list",             "",               "List available tools"],
            ["-ti",  "--tools-install",          "<tool>",         "Install <tool>"],
            ["-tu",  "--tools-update",           "<tool>",         "Update <tool>"],
            ["-td",  "--tools-delete",           "<tool>",         "Delete <tool>"],
            ]
        },
        {"options": [
            ["-T",   "--target",                 "<target>",         "Set target server"],
            ["-a",   "--auth",                   "<auth>",           "Set authorization code"],
            ["-t",   "--threads",                "<threads>",        "Set number of threads"],
            ["-p",   "--proxy",                  "",                 "Set proxy"],
            ["-nv",  "--no-ssl-verify",          "",                 "Do not verify SSL connections"],
            ["-v",   "--version",                "",                 "Show script version and exit"],
            ["-h",   "--help",                   "",                 "Show this help message and exit"],
            ]
        },
        ]

def handle_tools_args(args):
    attributes_to_check = ['tools_install', 'tools_update', 'tools_delete']
    for attr in attributes_to_check:
        if getattr(args, attr, None) == []:
            setattr(args, attr, ["all"])
    return args

def parse_args():
    parser = argparse.ArgumentParser(add_help=False, usage=f"{SCRIPTNAME}.py <options>")
    parser.add_argument("-p",    "--proxy",           type=str)
    parser.add_argument("-nv",   "--no-ssl-verify",   action="store_true")
    parser.add_argument("-i",    "--init",            action="store_true")

    parser.add_argument("-np", "-pn",   "--project-new",     action="store_true")
    parser.add_argument("-lp", "-pl",   "--project-list",    action="store_true")
    parser.add_argument("-sp", "-ps",   "--project-start",   type=str)
    parser.add_argument("-ep", "-pe",   "--project-end",     type=str)
    parser.add_argument("-rp", "-pr",   "--project-reset",   type=str)
    parser.add_argument("-dp", "-pd",   "--project-delete",  type=str)

    parser.add_argument("-tl", "-lt",  "--tools-list",      action="store_true")
    parser.add_argument("-ti", "-it",  "--tools-install",   type=str, nargs="*")
    parser.add_argument("-tu", "-ut",  "--tools-update",    type=str, nargs="*")
    parser.add_argument("-td", "-dt",  "--tools-delete",    type=str, nargs="*")

    parser.add_argument("-T",    "--target",          type=str)
    parser.add_argument("-a",    "--auth",            type=str)
    parser.add_argument("-t",    "--threads",         type=int, default=20)
    parser.add_argument("-v",    "--version",         action="version", version=f"{SCRIPTNAME} {__version__}")

    parser.add_argument("--socket-address",          type=str, default=None)
    parser.add_argument("--port",                    type=str, default=None)
    parser.add_argument("--process-ident",           type=str, default=None)
    parser.add_argument("--debug",                   action="store_true")


    if len(sys.argv) == 1 or "-h" in sys.argv or "--help" in sys.argv:
        ptprinthelper.help_print(get_help(), SCRIPTNAME, __version__)
        sys.exit(0)

    args = parser.parse_args()
    if int(bool(args.project_start))+int(bool(args.project_end))+int(bool(args.project_reset))+int(bool(args.project_delete)) > 1:
        ptjsonlib.PtJsonLib().end_error("Cannot combine project --start/--end/--reset/--delete  arguments together", True)

    ptprinthelper.print_banner(SCRIPTNAME, __version__, False, 0)
    return args


def main():
    global SCRIPTNAME
    SCRIPTNAME = "ptmanager"
    requests.packages.urllib3.disable_warnings()
    args = handle_tools_args(parse_args())
    manager = PtManager(args)
    manager.run(args)


if __name__ == "__main__":
    main()
