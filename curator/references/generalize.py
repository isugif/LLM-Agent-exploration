"""Anchor generalization — strip tool-specific FACTS from a few-shot anchor, keep the SHAPE.

Prevention half of the DB3 defense (grounding is the detection half): before showing an anchor to
the model, mask its concrete values (flags, commands, versions) with placeholders. The model then
sees "what a section looks like" — how many items, which fields, the density — with nothing
tool-specific to copy, so every real token must come from the SOURCE.

Applied only to the leak-prone, fact-dense sections; low-leak sections (citations/source/etc.) keep
their real type-matched anchor for better style guidance. Structure (list lengths) is preserved so
the anchor still conveys typical density.
"""

from __future__ import annotations

from pydantic import BaseModel

from shared.sections.schemas import (
    ExecutionSection, InstallMethod, InstallSection, Option, OptionsSection,
    UsageExample, UsageSection,
)

# sections whose anchors carry copyable facts (flags/commands/versions)
LEAK_PRONE = {"usage", "options", "install", "execution"}


def generalize(section: str, obj: BaseModel) -> BaseModel:
    """Return a placeholder version of the anchor for leak-prone sections; else return it unchanged."""
    if section == "install" and isinstance(obj, InstallSection):
        return InstallSection(
            version="<x.y.z>",
            # keep the package-manager names (generic, not tool facts); mask the command
            methods=[InstallMethod(manager=m.manager, command=f"<{m.manager} install command for the tool>")
                     for m in obj.methods] or [InstallMethod(manager="conda", command="<install command>")],
            verify_command="<tool> --version",
            verify_expected="<tool> <x.y.z>" if obj.verify_expected else None,
            notes=["<one factual install note>"] if obj.notes else [],
        )
    if section == "usage" and isinstance(obj, UsageSection):
        return UsageSection(
            examples=[UsageExample(description="<what this invocation does>",
                                   command="<tool> <flags> <input>") for _ in obj.examples]
                     or [UsageExample(description="<what this does>", command="<tool> <flags> <input>")],
            note="<one factual usage note>" if obj.note else None,
        )
    if section == "options" and isinstance(obj, OptionsSection):
        n = min(len(obj.options) or 3, 3)             # a few placeholders convey "a flag table"
        return OptionsSection(
            options=[Option(flag="-<x> / --<long-name>", description="<what the flag does>", default=None)
                     for _ in range(n)],
        )
    if section == "execution" and isinstance(obj, ExecutionSection):
        return ExecutionSection(
            argv=["<tool>", "<flags...>", "{input}", "{out_dir}"],
            version_argv=["<tool>", "--version"] if obj.version_argv else None,
            install_hint="<install command>" if obj.install_hint else None,
        )
    return obj
