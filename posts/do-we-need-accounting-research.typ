// Simple numbering for non-book documents
#let equation-numbering = "(1)"
#let callout-numbering = "1"
#let subfloat-numbering(n-super, subfloat-idx) = {
  numbering("1a", n-super, subfloat-idx)
}

// Theorem configuration for theorion
// Simple numbering for non-book documents (no heading inheritance)
#let theorem-inherited-levels = 0

// Theorem numbering format (can be overridden by extensions for appendix support)
// This function returns the numbering pattern to use
#let theorem-numbering(loc) = "1.1"

// Default theorem render function
#let theorem-render(prefix: none, title: "", full-title: auto, body) = {
  if full-title != "" and full-title != auto and full-title != none {
    strong[#full-title.]
    h(0.5em)
  }
  body
}
// Some definitions presupposed by pandoc's typst output.
#let content-to-string(content) = {
  if content.has("text") {
    content.text
  } else if content.has("children") {
    content.children.map(content-to-string).join("")
  } else if content.has("body") {
    content-to-string(content.body)
  } else if content == [ ] {
    " "
  }
}

#let horizontalrule = line(start: (25%,0%), end: (75%,0%))

#let endnote(num, contents) = [
  #stack(dir: ltr, spacing: 3pt, super[#num], contents)
]

#show terms.item: it => block(breakable: false)[
  #text(weight: "bold")[#it.term]
  #block(inset: (left: 1.5em, top: -0.4em))[#it.description]
]

// Some quarto-specific definitions.

#show raw.where(block: true): set block(
    fill: luma(230),
    width: 100%,
    inset: 8pt,
    radius: 2pt
  )

#let block_with_new_content(old_block, new_content) = {
  let fields = old_block.fields()
  let _ = fields.remove("body")
  if fields.at("below", default: none) != none {
    // TODO: this is a hack because below is a "synthesized element"
    // according to the experts in the typst discord...
    fields.below = fields.below.abs
  }
  block.with(..fields)(new_content)
}

#let empty(v) = {
  if type(v) == str {
    // two dollar signs here because we're technically inside
    // a Pandoc template :grimace:
    v.matches(regex("^\\s*$")).at(0, default: none) != none
  } else if type(v) == content {
    if v.at("text", default: none) != none {
      return empty(v.text)
    }
    for child in v.at("children", default: ()) {
      if not empty(child) {
        return false
      }
    }
    return true
  }

}

// Subfloats
// This is a technique that we adapted from https://github.com/tingerrr/subpar/
#let quartosubfloatcounter = counter("quartosubfloatcounter")

#let quarto_super(
  kind: str,
  caption: none,
  label: none,
  supplement: str,
  position: none,
  subcapnumbering: "(a)",
  body,
) = {
  context {
    let figcounter = counter(figure.where(kind: kind))
    let n-super = figcounter.get().first() + 1
    set figure.caption(position: position)
    [#figure(
      kind: kind,
      supplement: supplement,
      caption: caption,
      {
        show figure.where(kind: kind): set figure(numbering: _ => {
          let subfloat-idx = quartosubfloatcounter.get().first() + 1
          subfloat-numbering(n-super, subfloat-idx)
        })
        show figure.where(kind: kind): set figure.caption(position: position)

        show figure: it => {
          let num = numbering(subcapnumbering, n-super, quartosubfloatcounter.get().first() + 1)
          show figure.caption: it => block({
            num.slice(2) // I don't understand why the numbering contains output that it really shouldn't, but this fixes it shrug?
            [ ]
            it.body
          })

          quartosubfloatcounter.step()
          it
          counter(figure.where(kind: it.kind)).update(n => n - 1)
        }

        quartosubfloatcounter.update(0)
        body
      }
    )#label]
  }
}

// callout rendering
// this is a figure show rule because callouts are crossreferenceable
#show figure: it => {
  if type(it.kind) != str {
    return it
  }
  let kind_match = it.kind.matches(regex("^quarto-callout-(.*)")).at(0, default: none)
  if kind_match == none {
    return it
  }
  let kind = kind_match.captures.at(0, default: "other")
  kind = upper(kind.first()) + kind.slice(1)
  // now we pull apart the callout and reassemble it with the crossref name and counter

  // when we cleanup pandoc's emitted code to avoid spaces this will have to change
  let old_callout = it.body.children.at(1).body.children.at(1)
  let old_title_block = old_callout.body.children.at(0)
  let children = old_title_block.body.body.children
  let old_title = if children.len() == 1 {
    children.at(0)  // no icon: title at index 0
  } else {
    children.at(1)  // with icon: title at index 1
  }

  // TODO use custom separator if available
  // Use the figure's counter display which handles chapter-based numbering
  // (when numbering is a function that includes the heading counter)
  let callout_num = it.counter.display(it.numbering)
  let new_title = if empty(old_title) {
    [#kind #callout_num]
  } else {
    [#kind #callout_num: #old_title]
  }

  let new_title_block = block_with_new_content(
    old_title_block,
    block_with_new_content(
      old_title_block.body,
      if children.len() == 1 {
        new_title  // no icon: just the title
      } else {
        children.at(0) + new_title  // with icon: preserve icon block + new title
      }))

  align(left, block_with_new_content(old_callout,
    block(below: 0pt, new_title_block) +
    old_callout.body.children.at(1)))
}

// 2023-10-09: #fa-icon("fa-info") is not working, so we'll eval "#fa-info()" instead
#let callout(body: [], title: "Callout", background_color: rgb("#dddddd"), icon: none, icon_color: black, body_background_color: white) = {
  block(
    breakable: false,
    fill: background_color,
    stroke: (paint: icon_color, thickness: 0.5pt, cap: "round"),
    width: 100%,
    radius: 2pt,
    block(
      inset: 1pt,
      width: 100%,
      below: 0pt,
      block(
        fill: background_color,
        width: 100%,
        inset: 8pt)[#if icon != none [#text(icon_color, weight: 900)[#icon] ]#title]) +
      if(body != []){
        block(
          inset: 1pt,
          width: 100%,
          block(fill: body_background_color, width: 100%, inset: 8pt, body))
      }
    )
}




#let article(
  title: none,
  subtitle: none,
  authors: none,
  keywords: (),
  date: none,
  abstract-title: none,
  abstract: none,
  thanks: none,
  cols: 1,
  lang: "en",
  region: "US",
  font: none,
  fontsize: 11pt,
  title-size: 1.5em,
  subtitle-size: 1.25em,
  heading-family: none,
  heading-weight: "bold",
  heading-style: "normal",
  heading-color: black,
  heading-line-height: 0.65em,
  mathfont: none,
  codefont: none,
  linestretch: 1,
  sectionnumbering: none,
  linkcolor: none,
  citecolor: none,
  filecolor: none,
  toc: false,
  toc_title: none,
  toc_depth: none,
  toc_indent: 1.5em,
  doc,
) = {
  // Set document metadata for PDF accessibility
  set document(title: title, keywords: keywords)
  set document(
    author: authors.map(author => content-to-string(author.name)).join(", ", last: " & "),
  ) if authors != none and authors != ()
  set par(
    justify: true,
    leading: linestretch * 0.65em
  )
  set text(lang: lang,
           region: region,
           size: fontsize)
  set text(font: font) if font != none
  show math.equation: set text(font: mathfont) if mathfont != none
  show raw: set text(font: codefont) if codefont != none

  set heading(numbering: sectionnumbering)

  show link: set text(fill: rgb(content-to-string(linkcolor))) if linkcolor != none
  show ref: set text(fill: rgb(content-to-string(citecolor))) if citecolor != none
  show link: this => {
    if filecolor != none and type(this.dest) == label {
      text(this, fill: rgb(content-to-string(filecolor)))
    } else {
      text(this)
    }
   }

  place(
    top,
    float: true,
    scope: "parent",
    clearance: 4mm,
    block(below: 1em, width: 100%)[

      #if title != none {
        align(center, block(inset: 2em)[
          #set par(leading: heading-line-height) if heading-line-height != none
          #set text(font: heading-family) if heading-family != none
          #set text(weight: heading-weight)
          #set text(style: heading-style) if heading-style != "normal"
          #set text(fill: heading-color) if heading-color != black

          #text(size: title-size)[#title #if thanks != none {
            footnote(thanks, numbering: "*")
            counter(footnote).update(n => n - 1)
          }]
          #(if subtitle != none {
            parbreak()
            text(size: subtitle-size)[#subtitle]
          })
        ])
      }

      #if authors != none and authors != () {
        let count = authors.len()
        let ncols = calc.min(count, 3)
        grid(
          columns: (1fr,) * ncols,
          row-gutter: 1.5em,
          ..authors.map(author =>
              align(center)[
                #author.name \
                #author.affiliation \
                #author.email
              ]
          )
        )
      }

      #if date != none {
        align(center)[#block(inset: 1em)[
          #date
        ]]
      }

      #if abstract != none {
        block(inset: 2em)[
        #text(weight: "semibold")[#abstract-title] #h(1em) #abstract
        ]
      }
    ]
  )

  if toc {
    let title = if toc_title == none {
      auto
    } else {
      toc_title
    }
    block(above: 0em, below: 2em)[
    #outline(
      title: toc_title,
      depth: toc_depth,
      indent: toc_indent
    );
    ]
  }

  doc
}

#set table(
  inset: 6pt,
  stroke: none
)
#let brand-color = (:)
#let brand-color-background = (:)
#let brand-logo = (:)

#set page(
  paper: "a4",
  margin: (x: 2cm,y: 2cm,),
  numbering: "1",
  columns: 1,
)

#show: doc => article(
  title: [Do we need accounting research?],
  authors: (
    ( name: [Ian D. Gow],
      affiliation: [],
      email: [] ),
    ),
  date: [22 December 2021],
  font: ("Libertinus Serif",),
  fontsize: 10.5pt,
  heading-family: ("Libertinus Serif",),
  mathfont: ("New Computer Modern Math",),
  linkcolor: [\#0000FF],
  toc_title: [Table of contents],
  toc_depth: 3,
  doc,
)

#emph[Originally published on #link("https://www.linkedin.com/pulse/do-we-need-accounting-research-ian-gow/")[LinkedIn] on 2021-12-22 (UTC).]

Obviously we don't #emph[need] accounting research in the same way that we need research into Covid vaccines or cures for cancer. So a better question might be: does accounting research justify the cost incurred to create it?

I plan to tackle this question in a series of short pieces. Each piece will investigate an aspect of how research might be useful and evaluate whether accounting research delivers in that regard.

One way that accounting research might be useful is through teaching. One channel would be “bringing research into the classroom” or, essentially, accounting research informing the content of what is taught to students. Another channel is more indirect, namely, the notion that doing research makes for better teachers. This in turn could have multiple mechanisms. One is a kind of filter: having the intellectual horsepower to do research makes one apt to be a better teacher. Another is a kind of weight-training for the mind: doing research sharpens one's mind, and students benefit from being taught by intellectually athletic professors.

Another way that accounting research could be useful is more direct. It could be that accounting research expands human knowledge in ways that do not rely on classroom teaching for transmission. For example, accounting research might directly influence regulators and practitioners.

= Spoiler alert!
<spoiler-alert>
In those subsequent pieces, I will argue that the benefits of contemporary accounting research are largely non-existent, or at least nowhere near the costs required to generate them. A good case can be made that modern accounting research started with #link("https://doi.org/10.2307/2490232")[Ball and Brown (1968)] and had very productive period over subsequent decades. But since the turn of the century, accounting research seems to have accomplished very little.

The idea that accounting research informs teaching seems very flimsy. As I've #link("https://iangow.github.io/notes/published/accounting_education.html")[observed] elsewhere, a substantial amount of accounting teaching is learning the application of accounting standards in a mechanical fashion, which has no connection to the overwhelming bulk of accounting research today. The impact of accounting research on practitioners and regulators seems close to zero.

As for accounting research sharpening one's mind, a seemingly increasingly popular mode of accounting research is what I have elsewhere termed “#link("https://www.linkedin.com/pulse/p-hacking-accounting-research-ian-gow/")[blind p-hacking]”. Far from enhancing one's ability to teach, this approach is best suited to researchers with no understanding of (or interest in) how the real world works, which seems a poor basis for pedagogical insight.

= What are the costs?
<what-are-the-costs>
So much for the (lack of) benefits. What about the costs? One view might be that accounting research is a harmless activity that keeps accounting professors out of danger's way when they're not teaching. But research surely has real costs.

At the top schools, the bulk of a faculty member's salary is attributable to research, though this proportion arguably declines as one moves down the research pecking order. But let's say that the cost of a typical faculty member in the United States that is attributable to research (salary and research costs) is US\$100,000 per year. Hasselback lists data for over 1,000 schools. If there are (on average) two faculty members paid mostly for their research at each of these schools, then we have 2,000 academics in this category in the United States. That's \$200 million per year. Multiplying by \~20, we have \$4 billion as the cost of accounting research in the United States this century (and this ignores the increasing amount of accounting research that is being done outside the United States).

One could quibble with this calculation for sure, but it's probably well within an order of magnitude of the true cost (and may well be too low). This \$4 billion is not a trivial sum. The NIH #link("https://nlmdirector.nlm.nih.gov/2021/11/17/turning-talent-into-treasure/")[says] it has received \$4.9 billion for research projects on Covid-19, and I think it would be very difficult to make the case that the value of accounting research comes even remotely close to the value of what has been learned about Covid-19 in the last couple of years (and I doubt the potential contributions of #emph[incremental] research dollars in the two areas are comparable either).

Does anyone seriously believe that accounting research over the last 20 years was worth billions of dollars?

= What might we do about this?
<what-might-we-do-about-this>
A natural question might be: What do we do about this? This is a tricky one to answer due to the complex institutional forces driving the “demand” for accounting research. So this question likely requires some focused follow-up pieces in its own right.

For now, I merely \[slightly mis\]quote #link("https://www.chronicle.com/article/when-disciplines-hit-dead-ends")[Noah Smith], an economist, who suggests that “the number of \[accounting\] research-doing professors is determined not by the need for actual research, but by the demand for … \[accounting\] education.” I would add that the demand for accounting research-doing professors has probably grown #emph[more than] the demand for accounting education as more universities have decided that they are research institutions and gradually replaced teaching specialists with more research-oriented faculty members.
