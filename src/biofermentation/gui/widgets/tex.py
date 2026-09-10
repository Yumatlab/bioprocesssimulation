"""Turning the TeX fragments of the database into something Qt can draw.

parameterTab.tex, variableTab.shorttex and tex_unit hold fragments like
c_{XL}, pO_{2w} or gl^{-1}. MATLAB hands them to its TeX interpreter; Qt
labels understand a subset of HTML, which covers exactly the two things these
fragments use — subscripts and superscripts.

Anything not recognised is left alone rather than mangled. A label that reads
a little raw is better than one that silently drops a symbol.
"""

import html
import re

# \alpha and friends, as they appear in parameterTab.tex.
GREEK = {
    "alpha": "α",
    "beta": "β",
    "gamma": "γ",
    "delta": "δ",
    "Delta": "Δ",
    "epsilon": "ε",
    "eta": "η",
    "theta": "θ",
    "vartheta": "ϑ",
    "kappa": "κ",
    "lamda": "λ",  # the database spells it without the b
    "lambda": "λ",
    "mu": "µ",
    "nu": "ν",
    "rho": "ρ",
    "sigma": "σ",
    "tau": "τ",
    "phi": "φ",
    "chi": "χ",
    "psi": "ψ",
    "omega": "ω",
}

_GROUP = re.compile(r"([_^])\{([^{}]*)\}")
_SINGLE = re.compile(r"([_^])(\w)")
_COMMAND = re.compile(r"\\(?:text(?:it|bf|rm)\{([^{}]*)\}|([A-Za-z]+))")


def tex_to_html(text: str | None) -> str:
    """A TeX fragment as Qt rich text. Empty in, empty out."""
    if not text:
        return ""

    def command(match: re.Match) -> str:
        inner, name = match.group(1), match.group(2)
        if inner is not None:
            return inner
        return GREEK.get(name, name)

    rendered = _COMMAND.sub(command, str(text))
    rendered = html.escape(rendered, quote=False)

    def script(match: re.Match) -> str:
        tag = "sub" if match.group(1) == "_" else "sup"
        return f"<{tag}>{match.group(2)}</{tag}>"

    # Repeatedly, because _GROUP only matches a group with no braces inside
    # it. \tau_{pO_{2}} resolves from the inside out; one pass would leave
    # the outer braces standing in the label.
    for _ in range(8):
        replaced = _GROUP.sub(script, rendered)
        if replaced == rendered:
            break
        rendered = replaced
    return _SINGLE.sub(script, rendered)


def tex_label(text: str | None, unit: str | None = None) -> str:
    """A label with its unit in brackets, both rendered."""
    body = tex_to_html(text)
    if unit:
        return f"{body} [{tex_to_html(unit)}]"
    return body
