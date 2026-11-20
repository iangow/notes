# Advanced DuPont Decomposition (2017)

A reconstruction of the four-page handout by Ian D. Gow and Charles C.Y. Wang,
dated 8 February 2017. The authoritative reference is the attachment
`Advanced_DuPont_Handout.pdf` from the author's 23 April 2024 Gmail message
(subject: DuPont). Its PDF metadata records compilation on 23 April 2024;
the printed document date is 2017. The original attachment is preserved here
as `advanced_dupont-original.pdf`.

## Files and rendering

- `advanced_dupont.qmd`: editable Quarto source; prose, headings, lists and most
  notes are Markdown. The derivation retains recovered LaTeX for alignment and
  bracketed note markers.
- `advanced_dupont-tufte.tex`: minimal template using the installed
  `tufte-handout` class, with title/list spacing adjusted against the reference.
- `_quarto.yml`: standalone subproject, isolating this PDF from the parent
  website's HTML configuration.
- `advanced_dupont.pdf`: rendered reconstruction.
- `advanced_dupont-original.pdf`: unchanged reference attachment.

From this directory, run:

```sh
quarto render
```

Requires Quarto and a system TeX installation with `tufte-latex`, `amsmath`,
`enumitem` and the Tufte class's dependencies (including Palatino/Pazo fonts).
The source selects system pdfLaTeX (`latex-tinytex: false`) because the local
TinyTeX installation lacks the Tufte class. Automatic package installation is
disabled. Verified using Quarto 1.9.35 and MacPorts TeX Live 2025.

## Fidelity and editorial policy

The reconstruction preserves the title, authors, printed date, complete wording,
equations, section order, 11 numbered sidenotes, bracketed markers for notes
6-9, and the underlining of “exactly.” It uses the same US Letter page size,
Tufte body/margin columns, font families, running heads and four-page structure.
The page 1/2 split falls within the Spread definition; the page 2/3 split is
within conceptual note 2; Implementation starts on page 4.

All four rendered pages were visually compared with the original. Extracted
body text and margin-note text match exactly after removing whitespace and
hyphens and normalizing apostrophes; equations and markers were also inspected
visually. This is a close reconstruction, not a pixel-identical reproduction:
minor list spacing, paragraph indentation and line-wrap differences remain,
particularly on page 3. Font/software versions and Markdown-to-LaTeX paragraph
handling can affect subsequent builds. Explicit spacing before the implementation
equations and an explicit page break retain the original organization.

Original inconsistencies are deliberately preserved, including “will illustrates,”
“deomposition,” the differing financing-rate terminology, and `OL + FA + E`
in the implementation balance-sheet equation (where `FL` would be expected).
These are transcription choices, not endorsements or silent corrections.

The surviving material in `../aussie_super.qmd` supplied the original LaTeX
algebra and much of the prose. Missing or altered wording was restored from
the PDF. No content was invented. A separate Typst version was unnecessary:
the original Tufte class directly supplies the required margin-note behavior.
