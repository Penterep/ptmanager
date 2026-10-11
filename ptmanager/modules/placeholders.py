"""Expand configured command placeholders into argument lists."""

import re


PLACEHOLDER_ARGUMENTS = {
    "mail": (
        ("server", "--testmail-server"),
        ("login", "--testmail-login"),
        ("password", "--testmail-password"),
    ),
    "www": (("url", "--testwww-url"),),
    "interface": ((None, "--interface"),),
}
PLACEHOLDER_CONFIGURATION_COMMANDS = {
    "mail": "ptmanager --set-mail <server> <login> <password>",
    "www": "ptmanager --set-www <url>",
    "interface": "ptmanager --set-interface <name>",
}
PLACEHOLDER_PATTERN = re.compile(r"\[\[([^\[\]]+)\]\]")


class PlaceholderError(ValueError):
    """A command placeholder is unknown, missing, or invalid."""


def placeholder_arguments(name: str, value) -> list[str]:
    """Validate one configured placeholder without exposing its values in errors."""
    if name not in PLACEHOLDER_ARGUMENTS:
        raise PlaceholderError(f"Unknown placeholder [[{name}]].")

    arguments = []
    for field, option in PLACEHOLDER_ARGUMENTS[name]:
        if field is None:
            field_value = value
        else:
            field_value = value.get(field) if isinstance(value, dict) else None
        if not isinstance(field_value, str) or not field_value.strip() or "\x00" in field_value:
            setting = f"{name}.{field}" if field else name
            raise PlaceholderError(
                f"SAT nemá nakonfigurovány vyžadované hodnoty ({setting}). "
                "Pro konfiguraci použij na SAT příkaz: "
                f"{PLACEHOLDER_CONFIGURATION_COMMANDS[name]}"
            )
        arguments.extend([option, field_value])
    return arguments


def expand_command(command: str, placeholders: dict) -> list[str]:
    """Replace standalone [[name]] arguments; configured values remain literal."""
    if not isinstance(command, str):
        raise PlaceholderError("Task command must be a string.")
    tokens = command.split()
    if not tokens:
        raise PlaceholderError("Task command is empty.")

    arguments = []
    for index, token in enumerate(tokens):
        match = PLACEHOLDER_PATTERN.fullmatch(token)
        if match:
            if index == 0:
                raise PlaceholderError("A placeholder cannot be used as the task executable.")
            name = match.group(1)
            if not isinstance(placeholders, dict):
                raise PlaceholderError("Placeholder configuration must be an object.")
            arguments.extend(placeholder_arguments(name, placeholders.get(name)))
        elif PLACEHOLDER_PATTERN.search(token):
            raise PlaceholderError("Command placeholders must be separate arguments.")
        else:
            arguments.append(token)
    return arguments
