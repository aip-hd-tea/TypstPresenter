# TypstPresenter

Maintainer: Jakob Moser <jakob@fsco.li>

Converts PowerPoint presentations (`*.pptx`) to Typst presentations (`*.typ`). The Typst library [diatypst](https://typst.app/universe/package/diatypst/) is used to typeset the slides, however, you can add your own _templates_ to this application if you want to support a different library.

## Verification tools (branch `ae/restart`)

The project is being restarted around [Touying](https://typst.app/universe/package/touying) for slides and CeTZ/Fletcher for diagrams. The first milestone is a pair of verification methods that check generated Typst output against the PPTX ground truth (element positions, proportions, text overflow):

- **Method A** — compile to PDF, extract geometry with PyMuPDF (`typstpresenter.verify.method_a`)
- **Method B** — Typst introspection probes read back via `typst query`, no PDF export (`typstpresenter.verify.method_b`)

See [docs/verification-methods.md](./docs/verification-methods.md) for the design, the feasibility study of introspection, and the measured comparison (summary: B is the primary gate — exact and id-matched; A is the rendered-output cross-check; both ~0.15 s per deck).

```bash
# check a generated file against its source
uv run typstpresenter verify talk.pptx talk.typ --method both

# regenerate the evaluation corpus and benchmark both methods
uv run typstpresenter benchmark -o verify_corpus --repeats 5

# test suite (needs the typst CLI on PATH)
uv run pytest tests/test_verify.py
```

## Installation and usage as uv tool

First, install `uv`: https://docs.astral.sh/uv/getting-started/installation/

Then, install TypstPresenter as a tool:

```
uv tool install git+https://github.com/aip-hd-tea/TypstPresenter.git
```

### Usage as uv tool

```bash
typstpresenter convert presentation.pptx presentation.typ
```

## Running without tool installation

```bash
# Example of converting and compiling ./tests/data/media.pptx to PDF
cd TypstPresenter
uv sync
uv run typstpresenter convert --compile ./tests/data/media.pptx
```

## Adding your own templates

1. Create a Typst file using your favorite presentation library.
2. Use [Jinja2 templating syntax](https://jinja.palletsprojects.com/en/stable/templates/) to add placeholders where the converted content should go.
3. Place that file in [`src/typstpresenter/templates/typst`](./src/typstpresenter/templates/typst).

> [!warning]
>
> You then also need to make sure to install the `typstpresenter` tool from your changed repo instead of mine; or run it directly from your repo (not as a tool) by prefixing the command with `uv run`; or bother the maintainer to implement something smarter.
