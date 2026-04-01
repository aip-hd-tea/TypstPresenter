# TypstPresenter

Maintainer: Jakob Moser <jakob@fsco.li>

Converts PowerPoint presentations (`*.pptx`) to Typst presentations (`*.typ`). The Typst library [diatypst](https://typst.app/universe/package/diatypst/) is used to typeset the slides, however, you can add your own _templates_ to this application if you want to support a different library.

## Installation

First, install `uv`: https://docs.astral.sh/uv/getting-started/installation/

Then, install TypstPresenter as a tool:

```
uv tool install git+https://github.com/jakob-moser-hd/TypstPresenter.git
```

## Usage

```bash
typstpresenter convert presentation.pdf presentation.typ
```

## Adding your own templates

1. Create a Typst file using your favorite presentation library.
2. Use [Jinja2 templating syntax](https://jinja.palletsprojects.com/en/stable/templates/) to add placeholders where the converted content should go.
3. Place that file in [`src/typstpresenter/templates/typst`](./src/typstpresenter/templates/typst).

> [!warning]
> 
> You then also need to make sure to install the `typstpresenter` tool from your changed repo instead of mine; or run it directly from your repo (not as a tool) by prefixing the command with `uv run`; or bother the maintainer to implement something smarter.
