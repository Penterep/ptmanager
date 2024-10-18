[![penterepTools](https://www.penterep.com/external/penterepToolsLogo.png)](https://www.penterep.com/)


## PTMANAGER - Penterep Script Management Tool

## Installation
```
pip install ptmanager
```

## Adding to PATH
If you're unable to invoke the script from your terminal, it's likely because it's not included in your PATH. You can resolve this issue by executing the following commands, depending on the shell you're using:

For Bash Users
```bash
echo "export PATH=\"`python3 -m site --user-base`/bin:\$PATH\"" >> ~/.bashrc
source ~/.bashrc
```

For ZSH Users
```bash
echo "export PATH=\"`python3 -m site --user-base`/bin:\$PATH\"" >> ~/.zshrc
source ~/.zshrc
```

## Usage examples
```
Usage:
   ptmanager <options>

Usage example:
   ptmanager --project-new --target <target> --auth <auth>
   ptmanager --project-start 1
   ptmanager --tools-install ptaxfr ptwebdiscover
```

## Options
```
Manager options:
   -pn  --project-new           Register new project
   -pl  --project-list          List available projects
   -ps  --project-start   <id>  Start project
   -pr  --project-reset   <id>  Restart project
   -pd  --project-delete  <id>  Delete project
   -pe  --project-end     <id>  End project

Tools options:
   -tl  --tools-list             List available tools
   -ti  --tools-install  <tool>  Install <tool>
   -tu  --tools-update   <tool>  Update <tool>
   -td  --tools-delete   <tool>  Delete <tool>

Options:
   -T   --target         <target>   Set target server
   -a   --auth           <auth>     Set authorization code
   -t   --threads        <threads>  Set number of threads
   -p   --proxy                     Set proxy
   -nv  --no-ssl-verify             Do not verify SSL connections
   -v   --version                   Show script version and exit
   -h   --help                      Show this help message and exit

```

## Dependencies
```
ptlibs
```

## License

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

## Warning

You are only allowed to run the tool against the websites which
you have been given permission to pentest. We do not accept any
responsibility for any damage/harm that this application causes to your
computer, or your network. Penterep is not responsible for any illegal
or malicious use of this code. Be Ethical!
